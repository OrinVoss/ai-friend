import logging
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

MODEL_CONTEXT = 180_000
COMPRESS_THRESHOLD = int(MODEL_CONTEXT * 0.8)

_TOKENIZER = None

def _get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            import tiktoken
            _TOKENIZER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _TOKENIZER = False
    return _TOKENIZER

def estimate_tokens(text: str) -> int:
    tok = _get_tokenizer()
    if tok:
        return len(tok.encode(text, disallowed_special=()))
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '　' <= c <= '〿')
    ascii_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    other = len(text) - cjk - ascii_chars - digits
    return max(1, int(cjk / 1.5 + ascii_chars / 4 + digits / 3 + other / 8))

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
        self._proactive_count = 0
        self._running = True
        self._compressed_summary: str = ""
        self._estimated_tokens_used: int = 0
        self._prompt_shown: bool = False
        self._react_iteration: int = 0
        self._react_messages: list[dict] | None = None
        self._max_tool_iterations: int = 5
        self._tool_registry: ToolRegistry | None = None

    # ── Web mode methods ──

    def process_message(self, user_input: str, on_token=None) -> str:
        from prompts.system import build_system_prompt
        self.short_term.add_turn("user", user_input)
        mem_ctx = self.retriever.retrieve_for_query(user_input)
        self.ltm.repo.insert_turn(self.turn_count, "user", user_input, str(self.personality.emotion.to_dict()))
        conv_hist = self.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=self.personality.config, emotion=self.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=self._compressed_summary, tools=self._tool_registry,
        )
        messages = [{"role": "system", "content": sys_prompt}]
        for t in reversed(self.short_term.get_all()):
            role = "assistant" if t.role == "assistant" else "user"
            if estimate_tokens(str(messages[-5:])) + estimate_tokens(t.content) > COMPRESS_THRESHOLD:
                break
            messages.insert(1, {"role": role, "content": t.content})
        user_msg = f"用户输入：{user_input}"
        if estimate_tokens(str(messages)) + estimate_tokens(user_msg) <= COMPRESS_THRESHOLD:
            messages.append({"role": "user", "content": user_msg})
        return self._react_loop(messages, on_token)

    def process_proactive(self, on_token=None) -> str:
        from prompts.system import build_system_prompt
        mem_ctx = self.retriever.retrieve_for_query("")
        topic = self._pick_proactive_topic()
        conv_hist = self.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=self.personality.config, emotion=self.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=self._compressed_summary, tools=self._tool_registry,
            is_proactive=True,
        )
        messages = [{"role": "system", "content": sys_prompt}]
        for t in reversed(self.short_term.get_all()):
            role = "assistant" if t.role == "assistant" else "user"
            if estimate_tokens(str(messages[-5:])) + estimate_tokens(t.content) > COMPRESS_THRESHOLD:
                break
            messages.insert(1, {"role": role, "content": t.content})
        messages.append({"role": "user", "content": f"[主动开启对话] 主题方向：{topic}"})
        return self._react_loop(messages, on_token)

    def _react_loop(self, messages: list[dict], on_token=None) -> str:
        from core.dispatcher import parse_tool_calls, execute_tool_calls, format_tool_results
        final_text = ""
        for _ in range(self._max_tool_iterations):
            resp = self.provider.generate(messages, stream=False if _ > 0 else True,
                                          on_token=on_token if _ == 0 else None)
            cleaned, calls = parse_tool_calls(resp)
            if not calls:
                final_text = cleaned
                break
            messages.append({"role": "assistant", "content": resp})
            results = execute_tool_calls(self._tool_registry, calls)
            messages.append({"role": "user", "content": format_tool_results(results)})

        if final_text:
            self.short_term.add_turn("assistant", final_text)
            self.ltm.repo.insert_turn(self.turn_count, "assistant", final_text, str(self.personality.emotion.to_dict()))
            self.turn_count += 1

        sentiment, sharing, energy = 0.1, False, 0.5
        try:
            sentiment, sharing, energy = self.consolidator.analyze_sentiment(final_text or "")
        except Exception:
            pass
        self.personality.apply_emotional_shift(sentiment, sharing, energy)
        if self.turn_count % 3 == 0:
            self.consolidator.add_pending(self.short_term.get_all()[-1])
            self.consolidator.consolidate(self.short_term, self.personality,
                                          max_facts=self.config.max_facts,
                                          max_experiences=self.config.max_experiences,
                                          max_reflections=self.config.max_reflections)
        if self.turn_count > 0 and self.turn_count % 10 == 0:
            self.personality.save(self.config.personality_file)
        return final_text

    # ── CLI run loop (unchanged) ──

    def run(self) -> None:
        if self.ui:
            self.ui.start()
            self.ui.display_banner(self.personality.config.name)
        else:
            print(f"\n=== {self.personality.config.name} ===\n")
        self.state = AgentState.BOOT
        self._on_boot()
        while self._running and self.state != AgentState.SHUTDOWN:
            try:
                handler = {
                    AgentState.IDLE: self._on_idle,
                    AgentState.PERCEIVE: self._on_perceive,
                    AgentState.THINK: self._on_think,
                    AgentState.ACT: self._on_act,
                    AgentState.REFLECT: self._on_reflect,
                }.get(self.state)
                if handler:
                    handler()
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received, shutting down...")
                self.state = AgentState.SHUTDOWN
            except Exception as e:
                logger.error(f"Error in state {self.state}: {e}", exc_info=True)
                if self.ui:
                    self.ui.display.print_error(str(e))
                time.sleep(1)
                self.state = AgentState.IDLE
        self._on_shutdown()

    def _on_boot(self) -> None:
        greeting = self.personality.config.first_run_greeting
        if not greeting:
            name = self.personality.config.name
            greeting = f"你好呀！我是{name}，很高兴认识你~ 我们可以随便聊聊，你有什么想说的吗？"
        if self.ui:
            self.ui.display.respond(greeting, prefix=self.personality.config.name)
        self.state = AgentState.IDLE

    def _on_idle(self) -> None:
        if not self._prompt_shown:
            print("\033[33m用户输入: \033[0m", end="", flush=True)
            self._prompt_shown = True
        user_input = self.ui.reader.read_line() if self.ui else None
        if user_input is not None:
            self.current_input = user_input
            self.state = AgentState.PERCEIVE
            return
        idle_duration = time.time() - self.last_activity_time
        if idle_duration > self.config.proactive_min_idle:
            proactivity_score = self._calculate_proactivity(idle_duration)
            if random.random() < proactivity_score:
                logger.info(f"Proactive trigger (score={proactivity_score:.2f})")
                self.current_input = None
                self.state = AgentState.THINK
                return
        time.sleep(0.1)

    def _on_perceive(self) -> None:
        user_input = self.current_input or ""
        if user_input.startswith("/"):
            self._handle_command(user_input)
            self.current_input = None
            self.state = AgentState.IDLE if self._running else AgentState.SHUTDOWN
            return
        self.short_term.add_turn("user", user_input)
        self.current_memory_context = self.retriever.retrieve_for_query(user_input)
        emotion_json = self.personality.emotion.to_dict()
        self.ltm.repo.insert_turn(self.turn_count, "user", user_input, str(emotion_json))
        logger.info(f"Turn {self.turn_count}: user input ({len(user_input)} chars)")
        self.state = AgentState.THINK

    def _on_think(self) -> None:
        from prompts.system import build_system_prompt
        is_proactive = self.current_input is None
        if self._react_messages is None:
            if is_proactive:
                self.current_memory_context = self.retriever.retrieve_for_query("")
                proactive_topic = self._pick_proactive_topic()
                user_message = f"[主动开启对话] 主题方向：{proactive_topic}"
            else:
                user_message = f"用户输入：{self.current_input or ''}"
            conversation_history = self.short_term.format_for_prompt(max_chars=3000)
            system_prompt = build_system_prompt(
                personality=self.personality.config, emotion=self.personality.emotion,
                memory_context=self.current_memory_context,
                conversation_history=conversation_history,
                is_proactive=is_proactive,
                compressed_summary=self._compressed_summary, tools=self._tool_registry,
            )
            messages = [{"role": "system", "content": system_prompt}]
            self._estimated_tokens_used = estimate_tokens(system_prompt)
            for t in reversed(self.short_term.get_all()):
                role = "assistant" if t.role == "assistant" else "user"
                msg = {"role": role, "content": t.content}
                msg_tokens = estimate_tokens(t.content)
                if self._estimated_tokens_used + msg_tokens > COMPRESS_THRESHOLD:
                    break
                messages.append(msg)
                self._estimated_tokens_used += msg_tokens
            messages = [messages[0]] + list(reversed(messages[1:]))
            if not is_proactive:
                user_msg = {"role": "user", "content": user_message}
                user_tokens = estimate_tokens(user_message)
                if self._estimated_tokens_used + user_tokens <= COMPRESS_THRESHOLD:
                    messages.append(user_msg)
                    self._estimated_tokens_used += user_tokens
                else:
                    self._compress_context(messages)
            self._react_messages = messages
            self._react_iteration = 0
        else:
            messages = self._react_messages
        self._prompt_shown = False
        is_tool_iteration = self._react_iteration > 0
        if is_tool_iteration:
            if self.ui:
                self.ui.display.print_system(f"思考中... (第{self._react_iteration}轮)")
            try:
                full_response = self.provider.generate(messages, stream=False)
            except ConnectionError as e:
                if self.ui:
                    self.ui.display.print_error(f"网络连接失败：{e}")
                self._reset_react()
                self.state = AgentState.REFLECT
                return
        else:
            if self.ui:
                self.ui.display.show_thinking()
            accumulated = []
            stream_done = False
            def on_token(token: str) -> None:
                if token and not stream_done:
                    if not accumulated:
                        if self.ui:
                            print("\r", end="", flush=True)
                            print(f"\033[1;36m{self.personality.config.name}:\033[0m ", end="", flush=True)
                    accumulated.append(token)
                    if self.ui:
                        print(token, end="", flush=True)
            try:
                full_response = self.provider.generate(messages, stream=True, on_token=on_token)
            except ConnectionError as e:
                if self.ui:
                    self.ui.display.print_error(f"网络连接失败：{e}")
                self._reset_react()
                self.state = AgentState.REFLECT
                return
            stream_done = True
            if self.ui:
                print()
        cleaned_text, tool_calls = parse_tool_calls(full_response)
        self.current_response = cleaned_text
        self._tool_calls_pending = tool_calls
        self._react_iteration += 1
        if self._react_messages is not None:
            self._react_messages.append({"role": "assistant", "content": full_response})
        self.state = AgentState.ACT

    def _on_act(self) -> None:
        tool_calls = getattr(self, '_tool_calls_pending', []) or []
        if tool_calls:
            if self._react_iteration > self._max_tool_iterations:
                if self.ui:
                    self.ui.display.print_system("工具调用次数已达上限")
                self._finish_react_response()
                return
            if self.ui:
                self.ui.display.print_system(f"执行 {len(tool_calls)} 个工具...")
            results = execute_tool_calls(self._tool_registry, tool_calls)
            result_text = format_tool_results(results)
            if self._react_messages is not None:
                self._react_messages.append({"role": "user", "content": result_text})
            no_valid_tool = all(not r["success"] for r in results)
            fake = contains_fake_action(self.current_response) and no_valid_tool
            if fake and self._react_iteration < self._max_tool_iterations:
                self._react_messages.append({
                    "role": "user",
                    "content": "你刚才说自己已经执行了操作，但没有成功调用任何工具。如果需要执行操作，请使用 <tool_call> 调用对应的工具。如果不需要工具，直接回复用户即可。",
                })
            self.state = AgentState.THINK
            return
        self._finish_react_response()

    def _finish_react_response(self) -> None:
        response = self.current_response
        if response:
            if self._react_iteration <= 1:
                pass
            else:
                if self.ui:
                    self.ui.display.respond(response, prefix=self.personality.config.name)
            self.short_term.add_turn("assistant", response)
            self.ltm.repo.insert_turn(self.turn_count, "assistant", response, str(self.personality.emotion.to_dict()))
            self.turn_count += 1
            self.last_activity_time = time.time()
        self._reset_react()
        self.state = AgentState.REFLECT

    def _reset_react(self) -> None:
        self._react_messages = None
        self._react_iteration = 0
        self._tool_calls_pending = []

    def _on_reflect(self) -> None:
        if self.current_response:
            sentiment = 0.1
            personal_sharing = False
            topic_energy = 0.5
            if self.short_term.get_all():
                last_user = self.short_term.get_all()[-1]
                if last_user.role == "user":
                    sentiment, personal_sharing, topic_energy = self.consolidator.analyze_sentiment(last_user.content)
            self.personality.apply_emotional_shift(sentiment, personal_sharing, topic_energy)
        emotional_intensity = abs(self.personality.emotion.valence)
        idle_duration = time.time() - self.last_activity_time
        if self.consolidator.should_consolidate(self.turn_count, emotional_intensity, idle_duration, self.config):
            self.consolidator.consolidate(self.short_term, self.personality,
                                          max_facts=self.config.max_facts,
                                          max_experiences=self.config.max_experiences,
                                          max_reflections=self.config.max_reflections)
        for t in list(self.short_term.get_all())[-2:]:
            self.consolidator.add_pending(t)
        if self.turn_count % 10 == 0:
            self.personality.save(self.config.personality_file)
        self.current_response = ""
        self.state = AgentState.IDLE

    def _on_shutdown(self) -> None:
        if hasattr(self, 'consolidator'):
            self.consolidator.consolidate(self.short_term, self.personality,
                                          max_facts=self.config.max_facts,
                                          max_experiences=self.config.max_experiences,
                                          max_reflections=self.config.max_reflections)
        self.personality.save(self.config.personality_file)
        if self.ui:
            self.ui.stop()
        print(f"\n\033[1;36m{self.personality.config.name} 记下了你们的对话。下次见~\033[0m")

    def _handle_command(self, cmd: str) -> None:
        cmd = cmd.strip().lower()
        if cmd in ("/exit", "/quit"):
            self._running = False
        elif cmd == "/save":
            self.consolidator.consolidate(self.short_term, self.personality,
                                          max_facts=self.config.max_facts,
                                          max_experiences=self.config.max_experiences,
                                          max_reflections=self.config.max_reflections)
            self.personality.save(self.config.personality_file)
            if self.ui:
                self.ui.display.print_system("记忆已保存")
        elif cmd == "/mood":
            if self.ui:
                e = self.personality.emotion
                self.ui.display.print_mood(f"{e.dominant_emotion} (valence={e.valence:.2f}, arousal={e.arousal:.2f})")
        elif cmd == "/status":
            rel = self.ltm.get_relationship()
            facts = self.ltm.get_all_active_facts()
            exps = self.ltm.get_recent_experiences(5)
            if self.ui:
                self.ui.display.print_system(f"对话轮次: {self.turn_count} | 记忆事实: {len(facts)} | 共享体验: {len(exps)}")
                for dim, val in rel.items():
                    self.ui.display.print_system(f"  关系 {dim}: {val:.2f}")
        elif cmd == "/forget":
            self.short_term.clear()
            if self.ui:
                self.ui.display.print_system("短期记忆已清除")
        elif cmd == "/help":
            if self.ui:
                self.ui.display_help()
        else:
            if self.ui:
                self.ui.display.print_system(f"未知命令: {cmd}")

    def _calculate_proactivity(self, idle_duration: float) -> float:
        base = min(0.3, idle_duration / 600.0)
        hour = datetime.now().hour
        time_mod = 0.2 if 10 <= hour <= 21 else 0.1 if 7 <= hour <= 22 else 0.0
        e = self.personality.emotion
        emotion_mod = e.arousal * 0.2
        if e.dominant_emotion in ("melancholy", "sad", "frustrated", "afraid"):
            emotion_mod -= 0.15
        rel = self.ltm.get_relationship()
        intimacy_mod = rel.get("intimacy", 0.3) * 0.15
        familiarity_mod = min(rel.get("familiarity", 0.3) * 0.1, 0.1)
        recent_turns = self.short_term.get_recent(6)
        user_turns = [t for t in recent_turns if t.role == "user"][-3:]
        sentiment_mod = 0.0
        if user_turns:
            last = user_turns[-1].content
            if any(kw in last for kw in ["烦", "滚", "生气", "讨厌", "别烦", "不想", "别吵"]):
                sentiment_mod = -0.3
            if any(kw in last for kw in ["哈哈", "开心", "好看", "棒", "不错", "喜欢", "好"]):
                sentiment_mod = 0.1
        goodbye_count = sum(1 for t in recent_turns if any(kw in t.content for kw in ["拜拜", "再见", "bye", "下次", "睡了", "晚安"]))
        goodbye_penalty = min(goodbye_count * 0.15, 0.3)
        short_count = sum(1 for t in user_turns if len(t.content) < 8)
        short_penalty = min(short_count * 0.08, 0.2)
        score = base + time_mod + emotion_mod + intimacy_mod + familiarity_mod + sentiment_mod - goodbye_penalty - short_penalty
        return max(0.0, min(0.8, score))

    def _pick_proactive_topic(self) -> str:
        facts = self.ltm.get_all_active_facts(limit=5)
        experiences = self.ltm.get_recent_experiences(limit=3)
        topics = []
        if experiences:
            latest = experiences[0]
            topics.append(f"上次我们聊了 {latest.summary}")
        if facts:
            fact = random.choice(facts)
            topics.append(f"{fact.fact_key}的事情")
        topics.append("随便聊聊近况")
        return random.choice(topics)

    def _proactive_flag(self) -> bool:
        return self._proactive_count > 0 and self.current_input is None

    def _compress_context(self, messages: list[dict]) -> None:
        from prompts.system import CONTEXT_COMPRESS_PROMPT
        conv_parts = []
        for m in messages:
            if m["role"] == "system":
                continue
            label = "用户" if m["role"] == "user" else "你"
            content = m["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            conv_parts.append(f"{label}: {content}")
        conv_text = "\n".join(conv_parts)
        if not conv_text.strip():
            return
        if len(conv_text) > 8000:
            conv_text = conv_text[-8000:]
        try:
            prompt = CONTEXT_COMPRESS_PROMPT.format(conversation=conv_text)
            result = self.provider.generate([{"role": "user", "content": prompt}], stream=False)
            summary = result.strip()
            if summary:
                self._compressed_summary = summary
                self._estimated_tokens_used = 0
                self.short_term.clear()
                logger.info(f"Context compressed. Summary: {summary[:80]}...")
                if self.ui:
                    self.ui.display.print_system("已压缩对话上下文")
        except Exception as e:
            logger.warning(f"Context compression failed: {e}")
