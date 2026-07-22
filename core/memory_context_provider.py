"""Shared memory-context assembly for Agent 1/3 (think once, use everywhere).

Extracted from core/inner_drive.py (2026-07-22)：检索策略（memory_agent /
retriever / 空 query 分流 + 同消息 memo）与格式化（关系块+记忆块）集中到这里，
InnerDriveAgent 与 MessageHandler 通过薄委托复用同一份装配逻辑。
"""

import logging

logger = logging.getLogger(__name__)


class MemoryContextProvider:
    """Builds memory/relationship summaries once per user message."""

    def __init__(self, retriever, memory_agent=None):
        self._retriever = retriever
        self._memory_agent = memory_agent
        self._cs_memo: tuple[str, object] | None = None  # (user_input, MemoryAnswer | None)

    def build_summary(self, mem_ctx) -> str:
        """Format memory/relationship blocks for Agent 3 reuse."""
        from prompts.system import _build_relationship_block, _build_memory_block
        parts = [
            _build_relationship_block(mem_ctx),
            _build_memory_block(mem_ctx),
        ]
        return "\n\n".join(p for p in parts if p)

    def answer_for(self, user_input: str):
        """R1 memo：同一条消息内 memory_agent.answer() 只跑一次。
        返回 MemoryAnswer 或 None（未启用/失败/空 query）。"""
        if self._cs_memo and self._cs_memo[0] == user_input:
            return self._cs_memo[1]
        ma = None
        if self._memory_agent is not None and (user_input or "").strip():
            try:
                from core.async_utils import run_async
                ma = run_async(self._memory_agent.answer(user_input))
            except Exception as e:
                logger.warning(f"[inner_drive] memory agent failed, retriever fallback: {e}")
                ma = None
        self._cs_memo = (user_input, ma)
        return ma

    def summary_for(self, user_input: str) -> str:
        """Agent 1 prompt 的记忆上下文（全文）。memo 缓存 MemoryAnswer，
        Agent 3 的轻量渲染复用同一对象（L3-3）。"""
        if not (user_input or "").strip():
            # F3: 空 query 走 retriever 概览（现状逻辑保留）
            return self.build_summary(self._retriever.retrieve_for_query(user_input))
        ma = self.answer_for(user_input)
        if ma is not None:
            from memory.retrieval_pipeline import ContextBuilder
            full = ContextBuilder().build("agent1", ma)
            if full:
                logger.debug(f"[inner_drive] context via memory agent "
                             f"(confidence={ma.confidence})")
                return full
            logger.debug("[inner_drive] memory agent empty, retriever fallback")
        return self.build_summary(self._retriever.retrieve_for_query(user_input))

    @staticmethod
    def format_memory_answer(ma) -> str:
        """Thin wrapper around ContextBuilder for backward compatibility.
        Agent 1 receives the full memory context with confidence markers."""
        from memory.retrieval_pipeline import ContextBuilder
        return ContextBuilder().build("agent1", ma)
