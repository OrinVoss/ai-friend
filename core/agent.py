import json
import logging
import os
import random
import time
from datetime import datetime
from enum import Enum
from typing import Optional

from models.conversation import MemoryContext
from core.personality import Personality
from core.provider import KimiProvider
from core.dispatcher import parse_tool_calls, execute_tool_calls, format_tool_results, contains_fake_action
from memory.short_term import ConversationBuffer
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from memory.consolidation import MemoryConsolidator
from tools.traits import ToolRegistry
from ui.cli import ConsoleInterface
from config import Config
from core.context_manager import ContextManager, estimate_tokens, COMPRESS_THRESHOLD
from core.sleep_manager import SleepManager
from core.proactivity import ProactivityManager
from core.cli_controller import CliController
from core.message_handler import MessageHandler

logger = logging.getLogger(__name__)

class AgentState(Enum):
    BOOT = "boot"
    IDLE = "idle"
    PERCEIVE = "perceive"
    THINK = "think"
    ACT = "act"
    REFLECT = "reflect"
    SHUTDOWN = "shutdown"

class Agent:
    def __init__(self, personality: Personality, provider: KimiProvider,
                 ltm: LongTermMemory, retriever: MemoryRetriever,
                 consolidator: MemoryConsolidator, short_term: ConversationBuffer,
                 config: Config, ui: Optional[ConsoleInterface] = None):
        self.personality = personality
        self.provider = provider
        self.ltm = ltm
        self.retriever = retriever
        self.consolidator = consolidator
        self.short_term = short_term
        self.ui = ui
        self.config = config
        self.state = AgentState.BOOT
        self.turn_count = 0
        self.last_activity_time = time.time()
        self.current_input: str | None = None
        self.current_response: str = ""
        self.current_memory_context: MemoryContext | None = None
        self._tool_call_history: list[dict] = []  # recent tool call records
        # Sleep/wake cycle managed by SleepManager.
        # SL-001: sleep state file is namespaced per session_id so concurrent
        # sessions no longer share a single global .sleep_state.
        sleep_dir = os.path.dirname(os.path.abspath(config.personality_file))
        session_tag = getattr(config, "session_id", None) or "default"
        sleep_file = os.path.join(sleep_dir, f".sleep_state.{session_tag}")
        self._sleep = SleepManager(
            sleep_state_file=sleep_file,
            personality=personality, ltm=ltm, provider=provider,
            session_id=session_tag,
        )

        self._running = True
        self._context = ContextManager(provider=provider, short_term=short_term)
        self._proactive = ProactivityManager(
            personality=personality, ltm=ltm, short_term=short_term,
        )
        self._tool_failures: int = 0  # #165: degradation counter
        self._consecutive_negative = self.personality.emotion.consecutive_negative
        self._prompt_shown: bool = False
        self._react_iteration: int = 0
        self._react_messages: list[dict] | None = None
        self._max_tool_iterations: int = getattr(config, 'max_tool_iterations', 5)
        self._tool_registry: ToolRegistry = ToolRegistry()
        self._tool_calls_pending: list = []

        self._cli = CliController(self)
        self._messages = MessageHandler(self)

    def _max_tokens_for_emotion(self) -> int:
        base = self.config.max_tokens
        mapping = {
            "excited": 768, "joyful": 768, "surprised": 700,
            "engaged": base, "content": base, "trusting": base, "anticipating": base,
            "neutral": base,
            "anxious": 300, "afraid": 300,
            "melancholy": 256, "sad": 256,
            "frustrated": 256, "angry": 256, "disgusted": 256,
        }
        return mapping.get(self.personality.emotion.dominant_emotion, base)

    # ── Message entry points (delegate to MessageHandler) ──

    def process_message(self, user_input: str, on_token=None) -> str:
        return self._messages.handle_message(user_input, on_token)

    def process_proactive(self, on_token=None, *, intent=None) -> str:
        return self._messages.handle_proactive(on_token=on_token, intent=intent)

    def process_explore(self, intent=None) -> str | None:
        return self._messages.handle_explore(intent=intent)

    def decide_proactive_action(self, idle_duration: float):
        """Use inner drive to decide what proactive action to take."""
        from core.inner_drive import ProactiveIntent
        inner_drive = self._messages.ensure_inner_drive()
        return inner_drive.assess_proactive(idle_duration)

    def _react_loop(self, messages: list[dict], on_token=None, add_to_history: bool = True,
                    tool_registry=None, skip_post_process: bool = False) -> str:
        from core.dispatcher import parse_tool_calls, execute_tool_calls, format_tool_results, contains_fake_action
        registry = tool_registry if tool_registry is not None else self._tool_registry
        max_tok = self._max_tokens_for_emotion()
        final_text = ""
        fake_action_count = 0
        tools_were_called = False  # once real tools execute, "工具返回" in response is legitimate
        for _idx in range(self._max_tool_iterations):
            logger.debug(f"[react] iter={_idx+1}/{self._max_tool_iterations}")
            try:
                resp = self.provider.generate(
                    messages, stream=False if _idx > 0 else True,
                    on_token=on_token if _idx == 0 else None,
                    max_tokens=max_tok if _idx == 0 else max(384, max_tok * 2 // 3),
                )
                cleaned, calls = parse_tool_calls(resp)
                if not calls:
                    if contains_fake_action(resp) and fake_action_count < 3 and not tools_were_called:
                        fake_action_count += 1
                        logger.warning(f"[react] fake tool action detected (attempt {fake_action_count}/3)")
                        messages.append({"role": "assistant", "content": resp})
                        messages.append({"role": "user", "content":
                            "YOU DID NOT ACTUALLY CALL ANY TOOLS! "
                            "You only described using tools in your text (like "
                            '"calling web_fetch", "reading the link"), but you '
                            "never output <tool_call> XML tags.\n\n"
                            "If you need web content, search results, or file "
                            "contents, you MUST output:\n"
                            '<tool_call>\n{"name": "tool_name", "arguments": {...}}\n</tool_call>\n\n'
                            "Tools will execute and return results to you. "
                            "Answer again -- this time REALLY call the tools, "
                            "do NOT describe calling them."
                        })
                        continue
                    final_text = cleaned
                    break
                tools_were_called = True
                messages.append({"role": "assistant", "content": resp})
                results = execute_tool_calls(registry, calls)
                # #165: degradation tracking — 3 consecutive failures → degrade
                all_failed = all(not r["success"] for r in results)
                if all_failed:
                    self._tool_failures += 1
                    if self._tool_failures >= 3:
                        logger.warning(f"[react] degradation: {self._tool_failures} consecutive tool failures, skipping tools")
                        final_text = "抱歉，我暂时无法获取外部信息，让我直接回复你吧。"
                        break
                else:
                    self._tool_failures = 0  # reset on success
                for r in results:
                    self._tool_call_history.append({
                        "name": r["name"],
                        "success": r["success"],
                        "output": r["output"][:200],
                        "time": time.time(),
                    })
                if len(self._tool_call_history) > 20:
                    self._tool_call_history = self._tool_call_history[-20:]
                messages.append({"role": "user", "content": format_tool_results(results)})
            except Exception:
                logger.exception("[react] unexpected error in iteration")
                if not final_text:
                    final_text = "抱歉，我暂时无法处理，让我直接回复你吧。"
                break

        # AG-002: guard against empty response after loop exhaustion
        if not final_text:
            final_text = "抱歉，我暂时无法获取信息，让我直接回复你吧。"
        # AG-005: hard fallback after 3 fake action corrections
        if fake_action_count >= 3 and not tools_were_called:
            final_text = "让我直接回复你吧。"
        self._reset_react()

        if final_text:
            if add_to_history:
                self.short_term.add_turn("assistant", final_text)
                # #130: detect stage directions in assistant response → mark as tool_claim
                is_claim = any(
                    final_text.strip().startswith(p)
                    for p in ['（调用', '(调用', '（前奏', '(前奏', '（搜索', '(搜索']
                )
                self.ltm.repo.insert_turn_sync(
                    self.turn_count, "assistant", final_text,
                    str(self.personality.emotion.to_dict()),
                    is_tool_claim=is_claim,
                )
                self.turn_count += 1

        if not skip_post_process:
            self._process_emotion()
        return final_text

    def _process_emotion(self) -> None:
        """Run sentiment analysis and emotional shift after a response."""
        sentiment, sharing, energy = 0.1, False, 0.5
        last_user_turn = ""
        try:
            all_turns = self.short_term.get_all()
            for t in reversed(all_turns):
                if t.role == "user":
                    last_user_turn = t.content
                    break
            sentiment, sharing, energy = self.consolidator.analyze_sentiment(last_user_turn)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Sentiment analysis parse error: {e}")

        if sentiment < -0.5:
            self._consecutive_negative += 1
        elif sentiment > 0.1:
            self._consecutive_negative = max(0, self._consecutive_negative - 1)
        # Persist to EmotionalState so personality.save() captures it
        self.personality.emotion.consecutive_negative = self._consecutive_negative

        hurt_multiplier = 1.0 + self._consecutive_negative * 0.4
        sentiment *= hurt_multiplier
        old_dom = self.personality.emotion.dominant_emotion
        self.personality.apply_emotional_shift(sentiment, sharing, energy)
        new_dom = self.personality.emotion.dominant_emotion
        if old_dom != new_dom:
            logger.info(f"[emotion] {old_dom}->{new_dom} valence={self.personality.emotion.valence:+.2f} "
                        f"arousal={self.personality.emotion.arousal:.2f} sentiment={sentiment:+.2f} "
                        f"consec_neg={self._consecutive_negative}")

        self.personality.emotion.record_emotion_event(
            trigger=last_user_turn[:100] if last_user_turn else "",
            context=last_user_turn[:200] if last_user_turn else "",
        )
        if self.turn_count % 3 == 0:
            self.consolidator.add_pending(self.short_term.get_all()[-1])
            self.consolidator.consolidate(self.short_term, self.personality,
                                          max_facts=self.config.max_facts,
                                          max_experiences=self.config.max_experiences,
                                          max_reflections=self.config.max_reflections)

    # ── CLI run loop (delegate to CliController) ──

    def run(self) -> None:
        self._cli.run()

    def _reset_react(self) -> None:
        self._react_messages = None
        self._react_iteration = 0
        self._tool_calls_pending = []

    # ── Sleep/wake forwarding ──

    @property
    def _sleeping(self) -> bool:
        return self._sleep.is_sleeping

    async def _get_sleep_state(self) -> tuple[bool, str | None]:
        return await self._sleep.get_sleep_state()

    async def _generate_dream(self) -> str:
        return await self._sleep.generate_dream()

    # ── Proactivity forwarding ──

    def _check_rate_limit(self, action: str) -> bool:
        return self._proactive.check_rate_limit(action)

    def _calculate_proactivity(self, idle_duration: float) -> float:
        return self._proactive.calculate_proactivity(idle_duration)

    def _pick_proactive_topic(self) -> str:
        return self._proactive.pick_proactive_topic()
