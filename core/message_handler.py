"""Message entry points: process_message, process_proactive, process_explore.

Used by both Web path (web/server.py → WebAgent) and CLI path (main.py → Agent.run).
Each method builds a system prompt, assembles messages, and delegates to Agent._react_loop."""

import logging
import random
import time

from core.context_manager import estimate_tokens, COMPRESS_THRESHOLD

logger = logging.getLogger(__name__)


class MessageHandler:
    """Handles incoming messages: prompt building, message assembly, react delegation."""

    def __init__(self, agent):
        self._agent = agent

    @property
    def a(self):
        return self._agent

    def handle_message(self, user_input: str, on_token=None) -> str:
        from prompts.system import build_system_prompt
        a = self.a

        if a._sleeping:
            a.last_activity_time = time.time()
            return random.choice(["zzz...ZZZ...💤", "Zzzz...[翻身]", "zzzz...（小声梦话）", "Zzz...💤"])

        logger.info(f"[msg] turn={a.turn_count} len={len(user_input)}")

        idle = time.time() - a.last_activity_time
        a.current_input = user_input
        a.last_activity_time = time.time()
        a.short_term.add_turn("user", user_input)
        mem_ctx = a.retriever.retrieve_for_query(user_input)
        a.current_memory_context = mem_ctx
        a.ltm.repo.insert_turn(a.turn_count, "user", user_input, str(a.personality.emotion.to_dict()))
        conv_hist = a.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a._context.compressed_summary, tools=a._tool_registry,
            consecutive_negative=a._consecutive_negative,
            tool_call_history=a._tool_call_history,
            idle_duration=idle,
        )
        messages = self._build_messages(sys_prompt, user_input=f"用户输入：{user_input}")
        return a._react_loop(messages, on_token, add_to_history=True)

    def handle_proactive(self, on_token=None) -> str:
        from prompts.system import build_system_prompt
        a = self.a
        mem_ctx = a.retriever.retrieve_for_query("")
        topic = a._pick_proactive_topic()
        conv_hist = a.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a._context.compressed_summary, tools=a._tool_registry,
            is_proactive=True, consecutive_negative=a._consecutive_negative,
        )
        messages = self._build_messages(sys_prompt, user_input=f"[主动开启对话] 主题方向：{topic}")
        logger.info(f"[proactive] chat: topic={topic}")
        return a._react_loop(messages, on_token, add_to_history=False)

    def handle_explore(self) -> str | None:
        from prompts.system import build_system_prompt
        a = self.a
        mem_ctx = a.retriever.retrieve_for_query("")
        topic = a._pick_proactive_topic()
        conv_hist = a.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a._context.compressed_summary, tools=a._tool_registry,
            is_proactive=True, consecutive_negative=a._consecutive_negative,
            explore_mode=True,
        )
        messages = self._build_messages(sys_prompt, user_input=None)
        interests = getattr(a.personality.config, 'interests', [])
        interest_hint = ""
        if interests:
            picked = random.sample(interests, min(2, len(interests)))
            interest_hint = f"可以搜搜关于{'/'.join(picked)}的内容，或者看看最近有什么相关新闻。"
        messages.append({"role": "user", "content": f"[自由探索] 你现在闲着。{interest_hint}也可以翻翻文件、听听歌。**你必须真的调用工具去搜一下**——别直接说没啥。搜完了如果发现有特别有意思的，分享出来；实在没意思才说没啥。别搜太随机的东西——搜你真正感兴趣、觉得用户也会喜欢的。"})
        logger.info(f"[explore] start: topic={topic}")
        result = a._react_loop(messages, on_token=None, add_to_history=False)
        if result and len(result.strip()) > 30 and not result.startswith("搜索"):
            logger.info(f"[explore] shared: {len(result)} chars")
            return result
        logger.debug(f"[explore] silent: result={result[:80] if result else 'None'}")
        return None

    def _build_messages(self, sys_prompt: str, user_input: str | None) -> list[dict]:
        """Common message assembly: system prompt + history + user message + overflow handling."""
        a = self.a
        messages = [{"role": "system", "content": sys_prompt}]
        overflow = False
        for t in a.short_term.get_all_reversed():
            role = "assistant" if t.role == "assistant" else "user"
            if estimate_tokens(" ".join(m["content"][:200] for m in messages[-5:] if m["role"] != "system")) + estimate_tokens(t.content) > COMPRESS_THRESHOLD:
                overflow = True
                break
            messages.insert(1, {"role": role, "content": t.content})
        if overflow and a._context.compressed_summary:
            messages.insert(1, {"role": "system", "content": f"[对话历史摘要] {a._context.compressed_summary}"})
        if user_input:
            msg_tokens = sum(estimate_tokens(m["content"][:500]) for m in messages if m["role"] != "system")
            if msg_tokens + estimate_tokens(user_input) > COMPRESS_THRESHOLD:
                a._context.compress(messages)
            messages.append({"role": "user", "content": user_input})
        return messages
