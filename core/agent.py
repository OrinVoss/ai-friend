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
from core.provider import LLMProvider
from core.dispatcher import parse_tool_calls, execute_tool_calls, format_tool_results, contains_fake_action
from memory.short_term import ConversationBuffer
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever
from memory.consolidation import MemoryConsolidator
from tools.traits import ToolRegistry
from ui.cli import ConsoleInterface
from config import Config
from core.context_manager import ContextManager, estimate_tokens
from core.sleep_manager import SleepManager
from core.proactivity import ProactivityManager
from core.cli_controller import CliController
from core.message_handler import MessageHandler

logger = logging.getLogger(__name__)

# _react_loop 的降级/兜底文案（:259/:269/:274/:277）。命中时 assistant turn
# 标记 metadata.error_fallback=True：DB 与界面保留，但不再注入后续 prompt
# 历史——防止模型把 API 故障期的兜底当成真实对话，污染情绪与人格一致性
_FALLBACK_TEXTS = frozenset({
    "抱歉，我暂时无法获取外部信息，让我直接回复你吧。",
    "抱歉，我暂时无法处理，让我直接回复你吧。",
    "抱歉，我暂时无法获取信息，让我直接回复你吧。",
    "让我直接回复你吧。",
})


class AgentState(Enum):
    BOOT = "boot"
    IDLE = "idle"
    PERCEIVE = "perceive"
    THINK = "think"
    ACT = "act"
    REFLECT = "reflect"
    SHUTDOWN = "shutdown"

class Agent:
    def __init__(self, personality: Personality, provider: LLMProvider,
                 ltm: LongTermMemory, retriever: MemoryRetriever,
                 consolidator: MemoryConsolidator, short_term: ConversationBuffer,
                 config: Config, ui: Optional[ConsoleInterface] = None,
                 session_id: str = "default"):
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
        # #311: 互斥锁——Web 线程池 / driver 后台线程会并发进入 process_* 与
        # add_turn/increment_turn_count，保护回合号分配与共享可变状态
        import threading
        self._turn_lock = threading.RLock()
        self.last_activity_time = time.time()
        self.current_input: str | None = None
        self.current_response: str = ""
        self.current_memory_context: MemoryContext | None = None
        self._tool_call_history: list[dict] = []  # recent tool call records
        # Sleep/wake cycle managed by SleepManager.
        # SL-001: sleep state file is namespaced per session_id so concurrent
        # sessions no longer share a single global .sleep_state.
        # Sleep state is persisted in the project root (same directory as the DB)
        # rather than next to the personality file, which now lives in personalities/.
        sleep_dir = os.path.dirname(os.path.abspath(config.db_path))
        session_tag = session_id or "default"
        # 存一份供外部只读（message_handler 的 getattr(a, "session_id", None)
        # 依赖它做 InnerDriveState 命名/prompt 标记；此前从未存储，getattr
        # 静默回退 None——2026-07-21 验收发现）
        self.session_id = session_tag
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
            # M-11: 与 sleep state 同目录、按 session 命名，重建后限速恢复
            state_dir=sleep_dir, session_id=session_tag,
        )
        self._tool_failures: int = 0  # #165: degradation counter
        self._consecutive_negative = self.personality.emotion.consecutive_negative
        self._prompt_shown: bool = False
        self._react_iteration: int = 0
        self._max_tool_iterations: int = getattr(config, 'max_tool_iterations', 5)
        self._degrade_threshold: int = getattr(config, 'degrade_threshold', 3)   # #255: consecutive tool failures before degrading
        self._max_fake_actions: int = getattr(config, 'max_fake_actions', 3)     # #255: max fake action corrections
        self._tool_registry: ToolRegistry = ToolRegistry()
        self._tool_calls_pending: list = []

        self._cli = CliController(self)
        self._messages = MessageHandler(self)

    def _max_tokens_for_emotion(self) -> int:
        base = self.config.max_tokens
        mapping = {
            "excited": 512, "joyful": 512, "surprised": 448,
            "engaged": base, "content": base, "trusting": base, "anticipating": base,
            "neutral": base,
            "anxious": 128, "afraid": 128,
            "melancholy": 128, "sad": 128,
            "frustrated": 128, "angry": 128, "disgusted": 128,
        }
        return mapping.get(self.personality.emotion.dominant_emotion, base)

    # ── Message entry points (delegate to MessageHandler) ──

    # ── Public accessors for MessageHandler (avoid direct _attr access) ──

    def add_turn(self, role: str, content: str, metadata: dict | None = None) -> None:
        """Persist a conversation turn to short-term memory and the repository."""
        with self._turn_lock:  # #311: 序列化并发写入
            # #311: 先写库再写内存——DB 失败时两边都不留，避免"内存有、磁盘无"
            # metadata without the is_tool_claim key (e.g. {"sleep": True}) must
            # coerce to False — a raw .get() returns None and int(None) crashes
            # insert_turn, silently dropping the turn (#156 root cause).
            self.ltm.repo.insert_turn_sync(
                self.turn_count, role, content,
                str(self.personality.emotion.to_dict()),
                is_tool_claim=bool(metadata.get("is_tool_claim")) if metadata else False,
            )
            self.short_term.add_turn(role, content, metadata=metadata)

    def append_turn_atomic(self, role: str, content: str,
                           metadata: dict | None = None) -> None:
        """#311: add_turn + increment_turn_count 原子化——供不经 process_* 的
        引擎路径（sleep/wake 持久化等）使用，避免与用户消息线程交错。"""
        with self._turn_lock:
            self.add_turn(role, content, metadata=metadata)
            self.increment_turn_count()

    def record_tool_call(self, name: str, success: bool, output: str) -> None:
        """Append a tool call record, keeping the rolling window bounded."""
        self._tool_call_history.append({
            "name": name,
            "success": success,
            "output": output[:200],
            "time": time.time(),
        })
        if len(self._tool_call_history) > 20:
            self._tool_call_history = self._tool_call_history[-20:]

    def get_tool_call_history(self) -> list[dict]:
        return self._tool_call_history

    def set_current_input(self, user_input: str) -> None:
        self.current_input = user_input

    def increment_turn_count(self) -> None:
        with self._turn_lock:  # #311
            self.turn_count += 1

    def update_last_activity(self) -> None:
        self.last_activity_time = time.time()

    def get_compressed_summary(self) -> str:
        return self._context.compressed_summary

    def get_consecutive_negative(self) -> int:
        return self._consecutive_negative

    # ── Public thin accessors (L4-1: keep MessageHandler out of private attrs) ──

    @property
    def tool_registry(self):
        """Full tool registry; MessageHandler splits it into internal/external."""
        return self._tool_registry

    @property
    def tool_call_history(self) -> list[dict]:
        """Recent tool call records (read-only view)."""
        return self._tool_call_history

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    @property
    def compressed_summary(self) -> str:
        return self._context.compressed_summary

    @property
    def consecutive_negative(self) -> int:
        return self._consecutive_negative

    def pick_proactive_topic(self) -> str:
        return self._pick_proactive_topic()

    def compress_context(self, messages: list[dict]) -> None:
        """Trigger context compression when the token budget is exceeded."""
        self._context.compress(messages)

    def should_compress(self, estimated_tokens: int) -> bool:
        """T1: delegate to ContextManager's should_compress for unified threshold check."""
        return self._context.should_compress(estimated_tokens)

    # ── Message entry points (delegate to MessageHandler) ──

    # #311: 三个入口共用 _turn_lock（RLock）——整条消息交换互斥，
    # 用户消息 / 主动消息 / 并发请求不会交错修改回合号与短期记忆
    def process_message(self, user_input: str, on_token=None) -> str:
        with self._turn_lock:
            return self._messages.handle_message(user_input, on_token)

    def process_proactive(self, on_token=None, *, intent=None) -> str:
        with self._turn_lock:
            return self._messages.handle_proactive(on_token=on_token, intent=intent)

    def process_explore(self, intent=None) -> str | None:
        with self._turn_lock:
            return self._messages.handle_explore(intent=intent)

    def decide_proactive_action(self, idle_duration: float):
        """Use inner drive to decide what proactive action to take."""
        from core.inner_drive import ProactiveIntent
        inner_drive = self._messages.ensure_inner_drive()
        # #177: 传入近期话题，让 LLM 选话题时避开重复
        return inner_drive.assess_proactive(
            idle_duration, recent_topics=self._proactive.get_recent_topics())

    def _react_loop(self, messages: list[dict], on_token=None, add_to_history: bool = True,
                    tool_registry=None, skip_post_process: bool = False) -> str:
        """Orchestration entry for the ReAct-style tool/response loop.

        Kept as a single-underscore method because it is an internal
        orchestration primitive, but it is deliberately invoked by
        MessageHandler and is therefore part of the Agent public surface.
        """
        registry = tool_registry if tool_registry is not None else self._tool_registry
        # H-07: 每条消息重置降级计数——否则上一条消息消耗的失败额度会让
        # 本条消息 1 次失败就触发降级
        self._tool_failures = 0
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
                    source="react",
                )
                cleaned, calls = parse_tool_calls(resp)
                if not calls:
                    if contains_fake_action(resp) and fake_action_count < self._max_fake_actions and not tools_were_called:
                        fake_action_count += 1
                        logger.warning(f"[react] fake tool action detected (attempt {fake_action_count}/{self._max_fake_actions})")
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
                    if self._tool_failures >= self._degrade_threshold:
                        logger.warning(f"[react] degradation: {self._tool_failures} consecutive tool failures, skipping tools")
                        final_text = "抱歉，我暂时无法获取外部信息，让我直接回复你吧。"
                        break
                else:
                    self._tool_failures = 0  # reset on success
                for r in results:
                    self.record_tool_call(r["name"], r["success"], r["output"])
                messages.append({"role": "user", "content": format_tool_results(results, output_cap=self.config.dispatcher_output_cap)})
            except Exception:
                logger.exception("[react] unexpected error in iteration")
                if not final_text:
                    final_text = "抱歉，我暂时无法处理，让我直接回复你吧。"
                break

        # AG-002: guard against empty response after loop exhaustion
        if not final_text:
            final_text = "抱歉，我暂时无法获取信息，让我直接回复你吧。"
        # AG-005: hard fallback after max fake action corrections
        if fake_action_count >= self._max_fake_actions and not tools_were_called:
            final_text = "让我直接回复你吧。"
        self._reset_react()

        if final_text:
            if add_to_history:
                # #130: detect stage directions in assistant response → mark as tool_claim
                is_claim = any(
                    final_text.strip().startswith(p)
                    for p in ['（调用', '(调用', '（前奏', '(前奏', '（搜索', '(搜索']
                )
                # 错误兜底文案（:259/:269/:274/:277 四处降级文本）打标：
                # DB/界面照常保留，但 _build_messages 会跳过它们，
                # 不让模型把 API 故障期的兜底当成真实对话历史
                is_fallback = final_text.strip() in _FALLBACK_TEXTS
                self.add_turn("assistant", final_text,
                              metadata={"is_tool_claim": is_claim,
                                        "error_fallback": is_fallback})
                self.increment_turn_count()

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
        # #291: 经加锁 setter 写入，不再直接写字段
        self.personality.set_consecutive_negative(self._consecutive_negative)

        hurt_multiplier = 1.0 + self._consecutive_negative * 0.4
        sentiment *= hurt_multiplier
        old_dom = self.personality.emotion.dominant_emotion
        self.personality.apply_emotional_shift(sentiment, sharing, energy)
        new_dom = self.personality.emotion.dominant_emotion
        if old_dom != new_dom:
            logger.info(f"[emotion] {old_dom}->{new_dom} valence={self.personality.emotion.valence:+.2f} "
                        f"arousal={self.personality.emotion.arousal:.2f} sentiment={sentiment:+.2f} "
                        f"consec_neg={self._consecutive_negative}")

        # #291: 经 Personality 的加锁转发方法写 emotion_events deque
        self.personality.record_emotion_event(
            trigger=last_user_turn[:100] if last_user_turn else "",
            context=last_user_turn[:200] if last_user_turn else "",
        )
        interval = getattr(self.config, 'consolidation_interval', 5)
        if interval > 0 and self.turn_count % interval == 0:
            self.consolidator.add_pending(self.short_term.get_all()[-1])
            self.consolidator.consolidate(self.short_term, self.personality,
                                          max_facts=self.config.max_facts,
                                          max_experiences=self.config.max_experiences,
                                          max_reflections=self.config.max_reflections)

    # ── CLI run loop (delegate to CliController) ──

    def run(self) -> None:
        self._cli.run()

    def _reset_react(self) -> None:
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

    def check_rate_limit(self, action: str) -> bool:
        return self._proactive.check_rate_limit(action)

    def record_rate_limit(self, action: str) -> None:
        return self._proactive.record_rate_limit(action)

    def record_topic(self, topic: str) -> None:
        """#177: 记录 LLM 主路径选用的话题（供去重与 prompt 提示）。"""
        return self._proactive.record_topic(topic)

    # ── F1: silent 退避转发 ──

    def record_silent(self) -> None:
        """F1: 连续 silent 计数。"""
        self._proactive.record_silent()

    def reset_silents(self) -> None:
        """F1: 用户说话或主动消息发出后重置退避。"""
        self._proactive.reset_silents()

    def silent_cooldown_seconds(self) -> float:
        """F1: 按连续 silent 次数返回冷却秒数。"""
        return self._proactive.silent_cooldown_seconds()

    def _calculate_proactivity(self, idle_duration: float) -> float:
        return self._proactive.calculate_proactivity(idle_duration)

    def _pick_proactive_topic(self) -> str:
        return self._proactive.pick_proactive_topic()
