import json
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

# DeepSeek v4 uses a BPE tokenizer similar to GPT-4's cl100k_base.
# tiktoken's cl100k_base is a close approximation for context management.
# Falls back to character-based heuristic if tiktoken unavailable.
_TOKENIZER = None
_TOKENIZER_ENCODING = "cl100k_base"

def _get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            import tiktoken
            _TOKENIZER = tiktoken.get_encoding(_TOKENIZER_ENCODING)
        except (ImportError, Exception):
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
        e = self.personality.emotion
        neg_score = max(e.anger, e.sadness, e.disgust)
        if neg_score > 0.8:
            self._consecutive_negative = 4  # one push from breaking
        elif neg_score > 0.5:
            self._consecutive_negative = 2
        else:
            self._compressing = False  # recursion guard for _compress_context
        self._consecutive_negative = 0
        self._running = True
        self._compressed_summary: str = ""
        self._estimated_tokens_used: int = 0
        self._prompt_shown: bool = False
        self._react_iteration: int = 0
        self._react_messages: list[dict] | None = None
        self._max_tool_iterations: int = 5
        self._tool_registry: ToolRegistry = ToolRegistry()

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

    def process_message(self, user_input: str, on_token=None) -> str:
        from prompts.system import build_system_prompt
        self.current_input = user_input
        self.last_activity_time = time.time()
        self.short_term.add_turn("user", user_input)
        mem_ctx = self.retriever.retrieve_for_query(user_input)
        self.current_memory_context = mem_ctx
        self.ltm.repo.insert_turn(self.turn_count, "user", user_input, str(self.personality.emotion.to_dict()))
        conv_hist = self.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=self.personality.config, emotion=self.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=self._compressed_summary, tools=self._tool_registry,
            consecutive_negative=self._consecutive_negative,
        )
        messages = [{"role": "system", "content": sys_prompt}]
        overflow = False
        for t in self.short_term.get_all_reversed():
            role = "assistant" if t.role == "assistant" else "user"
            if estimate_tokens(" ".join(m["content"][:200] for m in messages[-5:] if m["role"] != "system")) + estimate_tokens(t.content) > COMPRESS_THRESHOLD:
                overflow = True
                break
            messages.insert(1, {"role": role, "content": t.content})
        if overflow and self._compressed_summary:
            messages.insert(1, {"role": "system", "content": f"[对话历史摘要] {self._compressed_summary}"})
        user_msg = f"用户输入：{user_input}"
        msg_tokens = sum(estimate_tokens(m["content"][:500]) for m in messages if m["role"] != "system")
        if msg_tokens + estimate_tokens(user_msg) > COMPRESS_THRESHOLD:
            self._compress_context(messages)
        messages.append({"role": "user", "content": user_msg})
        return self._react_loop(messages, on_token, add_to_history=True)

    def process_proactive(self, on_token=None) -> str:
        from prompts.system import build_system_prompt
        mem_ctx = self.retriever.retrieve_for_query("")
        topic = self._pick_proactive_topic()
        conv_hist = self.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=self.personality.config, emotion=self.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=self._compressed_summary, tools=self._tool_registry,
            is_proactive=True, consecutive_negative=self._consecutive_negative,
        )
        messages = [{"role": "system", "content": sys_prompt}]
        overflow = False
        for t in self.short_term.get_all_reversed():
            role = "assistant" if t.role == "assistant" else "user"
            if estimate_tokens(" ".join(m["content"][:200] for m in messages[-5:] if m["role"] != "system")) + estimate_tokens(t.content) > COMPRESS_THRESHOLD:
                overflow = True
                break
            messages.insert(1, {"role": role, "content": t.content})
        if overflow and self._compressed_summary:
            messages.insert(1, {"role": "system", "content": f"[对话历史摘要] {self._compressed_summary}"})
        messages.append({"role": "user", "content": f"[主动开启对话] 主题方向：{topic}"})
        return self._react_loop(messages, on_token, add_to_history=False)

    def _react_loop(self, messages: list[dict], on_token=None, add_to_history: bool = True) -> str:
        from core.dispatcher import parse_tool_calls, execute_tool_calls, format_tool_results
        max_tok = self._max_tokens_for_emotion()
        final_text = ""
        for _ in range(self._max_tool_iterations):
            resp = self.provider.generate(
                messages, stream=False if _ > 0 else True,
                on_token=on_token if _ == 0 else None,
                max_tokens=max_tok if _ == 0 else max(256, max_tok // 2),
            )
            cleaned, calls = parse_tool_calls(resp)
            if not calls:
                final_text = cleaned
                break
            messages.append({"role": "assistant", "content": resp})
            results = execute_tool_calls(self._tool_registry, calls)
            messages.append({"role": "user", "content": format_tool_results(results)})

        if final_text:
            if add_to_history:
                self.short_term.add_turn("assistant", final_text)
            self.ltm.repo.insert_turn(self.turn_count, "assistant", final_text, str(self.personality.emotion.to_dict()))
            self.turn_count += 1
        # Analyze USER input sentiment (not AI response), track consecutive hurt
        sentiment, sharing, energy = 0.1, False, 0.5
        try:
            all_turns = self.short_term.get_all()
            last_user_turn = ""
            for t in reversed(all_turns):
                if t.role == "user":
                    last_user_turn = t.content
                    break
            sentiment, sharing, energy = self.consolidator.analyze_sentiment(last_user_turn)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Sentiment analysis parse error: {e}")

        # Track consecutive insults for 破防 mechanism
        if sentiment < -0.5:
            self._consecutive_negative += 1
        elif sentiment > 0.1:
            self._consecutive_negative = max(0, self._consecutive_negative - 1)
        # neutral: keep current count

        # Amplify emotional damage based on consecutive attacks
        hurt_multiplier = 1.0 + self._consecutive_negative * 0.4
        sentiment *= hurt_multiplier
        self.personality.apply_emotional_shift(sentiment, sharing, energy)

        # Record significant emotion events
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
        # Personality save handled by _on_reflect (CLI) or WebAgent (Web)
        return final_text

    # ── CLI run loop ──

    def run(self) -> None:
        if self.ui:
            self.ui.start()
            self.ui.display_banner(self.personality.config.name)
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
            greeting = f"你好呀！我是{self.personality.config.name}，很高兴认识你~"
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
            if random.random() < self._calculate_proactivity(idle_duration):
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
        self.ltm.repo.insert_turn(self.turn_count, "user", user_input, str(self.personality.emotion.to_dict()))
        self.state = AgentState.THINK

    def _on_think(self) -> None:
        from prompts.system import build_system_prompt
        is_proactive = self.current_input is None
        if self._react_messages is None:
            if is_proactive:
                self.current_memory_context = self.retriever.retrieve_for_query("")
                user_message = f"[主动开启对话] 主题方向：{self._pick_proactive_topic()}"
            else:
                user_message = f"用户输入：{self.current_input or ''}"
            sys_prompt = build_system_prompt(
                personality=self.personality.config, emotion=self.personality.emotion,
                memory_context=self.current_memory_context,
                conversation_history=self.short_term.format_for_prompt(max_chars=3000),
                is_proactive=is_proactive, compressed_summary=self._compressed_summary,
                tools=self._tool_registry,
                consecutive_negative=self._consecutive_negative,
            )
            messages = [{"role": "system", "content": sys_prompt}]
            self._estimated_tokens_used = estimate_tokens(sys_prompt)
            for t in self.short_term.get_all_reversed():
                role = "assistant" if t.role == "assistant" else "user"
                msg_tokens = estimate_tokens(t.content)
                if self._estimated_tokens_used + msg_tokens > COMPRESS_THRESHOLD:
                    break
                messages.append({"role": role, "content": t.content})
                self._estimated_tokens_used += msg_tokens
            messages = [messages[0]] + list(reversed(messages[1:]))
            if not is_proactive:
                user_msg = {"role": "user", "content": user_message}
                if self._estimated_tokens_used + estimate_tokens(user_message) <= COMPRESS_THRESHOLD:
                    messages.append(user_msg)
                    self._estimated_tokens_used += estimate_tokens(user_message)
                else:
                    self._compress_context(messages)
            self._react_messages = messages
            self._react_iteration = 0
        else:
            messages = self._react_messages
        self._prompt_shown = False
        max_tok = self._max_tokens_for_emotion()
        if self._react_iteration > 0:
            if self.ui:
                self.ui.display.print_system(f"思考中... (第{self._react_iteration}轮)")
            try:
                full_response = self.provider.generate(messages, stream=False, max_tokens=128)
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
            def on_token(tok: str) -> None:
                if tok and not stream_done:
                    if not accumulated and self.ui:
                        print("\r", end="", flush=True)
                        print(f"\033[1;36m{self.personality.config.name}:\033[0m ", end="", flush=True)
                    accumulated.append(tok)
                    if self.ui:
                        print(tok, end="", flush=True)
            try:
                full_response = self.provider.generate(messages, stream=True, on_token=on_token, max_tokens=max_tok)
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
            if all(not r["success"] for r in results) and contains_fake_action(self.current_response):
                self._react_messages.append({"role": "user", "content": "你刚才说自己已经执行了操作，但没有成功调用任何工具。如果需要执行操作，请使用 <tool_call> 调用对应的工具。如果不需要工具，直接回复用户即可。"})
            self.state = AgentState.THINK
            return
        self._finish_react_response()

    def _finish_react_response(self) -> None:
        if self.current_response:
            if self._react_iteration > 1 and self.ui:
                self.ui.display.respond(self.current_response, prefix=self.personality.config.name)
            self.short_term.add_turn("assistant", self.current_response)
            self.ltm.repo.insert_turn(self.turn_count, "assistant", self.current_response, str(self.personality.emotion.to_dict()))
            self.turn_count += 1
            self.last_activity_time = time.time()
        self._reset_react()
        self.state = AgentState.REFLECT

    def _reset_react(self) -> None:
        self._react_messages = None
        self._react_iteration = 0
        self._tool_calls_pending = []

    def _on_reflect(self) -> None:
        # Sentiment analysis + emotional shift already done in _react_loop
        # (shared by both CLI and Web paths). _on_reflect handles only
        # consolidation, pending turns, and periodic save.
        ei = abs(self.personality.emotion.valence)
        idle = time.time() - self.last_activity_time
        if self.consolidator.should_consolidate(self.turn_count, ei, idle, self.config):
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
        self.consolidator.consolidate(self.short_term, self.personality,
                                      max_facts=self.config.max_facts,
                                      max_experiences=self.config.max_experiences,
                                      max_reflections=self.config.max_reflections)
        self.personality.save(self.config.personality_file)
        if self.ui:
            self.ui.stop()
        print(f"\n\033[1;36m{self.personality.config.name} 记下了你们的对话。下次见~\033[0m")

    def _handle_command(self, cmd: str) -> None:
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
        elif cmd == "/mood" and self.ui:
            e = self.personality.emotion
            self.ui.display.print_mood(f"{e.dominant_emotion} (v={e.valence:.2f} a={e.arousal:.2f})")
        elif cmd == "/status" and self.ui:
            rel = self.ltm.get_relationship()
            self.ui.display.print_system(f"轮次: {self.turn_count} | 事实: {len(self.ltm.get_all_active_facts())}")
            for k, v in rel.items():
                self.ui.display.print_system(f"  {k}: {v:.2f}")
        elif cmd == "/forget":
            self.short_term.clear()
            if self.ui:
                self.ui.display.print_system("短期记忆已清除")
        elif cmd == "/help" and self.ui:
            self.ui.display_help()
        elif self.ui:
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
        intimacy_mod = rel.get("intimacy", 0.3) * 0.15 + min(rel.get("familiarity", 0.3) * 0.1, 0.1)
        user_turns = [t for t in self.short_term.get_recent(6) if t.role == "user"][-3:]
        sentiment_mod = 0.0
        if user_turns:
            last = user_turns[-1].content
            if any(kw in last for kw in ["烦", "滚", "生气", "讨厌", "别烦", "不想", "别吵"]):
                sentiment_mod = -0.3
            elif any(kw in last for kw in ["哈哈", "开心", "好看", "棒", "不错", "喜欢", "好"]):
                sentiment_mod = 0.1
        goodbye = sum(1 for t in self.short_term.get_recent(6) if any(kw in t.content for kw in ["拜拜", "再见", "bye", "下次", "睡了", "晚安"]))
        short_c = sum(1 for t in user_turns if len(t.content) < 8)
        score = base + time_mod + emotion_mod + intimacy_mod + sentiment_mod - min(goodbye * 0.15, 0.3) - min(short_c * 0.08, 0.2)
        return max(0.0, min(0.8, score))

    def _pick_proactive_topic(self) -> str:
        exps = self.ltm.get_recent_experiences(limit=3)
        facts = self.ltm.get_all_active_facts(limit=5)
        topics = []
        if exps:
            topics.append(f"上次我们聊了 {exps[0].summary}")
        if facts:
            topics.append(f"{random.choice(facts).fact_key}的事情")
        topics.append("随便聊聊近况")
        return random.choice(topics)

    def _proactive_flag(self) -> bool:
        return self._proactive_count > 0 and self.current_input is None

    def _compress_context(self, messages: list[dict]) -> None:
        if self._compressing:
            return  # prevent recursive compression
        self._compressing = True
        try:
            self._do_compress(messages)
        finally:
            self._compressing = False

    def _do_compress(self, messages: list[dict]) -> None:
        from prompts.system import CONTEXT_COMPRESS_PROMPT
        parts = []
        for m in messages:
            if m["role"] == "system":
                continue
            content = m["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            parts.append(f"{'用户' if m['role'] == 'user' else '你'}: {content}")
        text = "\n".join(parts)
        if not text.strip():
            return
        if len(text) > 8000:
            text = text[-8000:]
        try:
            result = self.provider.generate([{"role": "user", "content": CONTEXT_COMPRESS_PROMPT.format(conversation=text)}], stream=False)
            if result.strip():
                self._compressed_summary = result.strip()
                self._estimated_tokens_used = 0
                self.short_term.clear()
                logger.info(f"Context compressed: {self._compressed_summary[:80]}")
        except Exception as e:
            logger.warning(f"Compression failed: {e}")
