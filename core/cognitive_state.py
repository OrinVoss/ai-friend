"""每轮消息的统一运行时状态（World State / Blackboard 雏形）。

每轮用户输入装配一次，Agent 1/2/3 与后处理消费同一份，
不再各自重新检索/理解（Think Once, Use Everywhere）。
"""
import logging
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)


@dataclass
class CognitiveState:
    """统一运行时状态（World State / Blackboard）。

    每轮用户输入装配一次，Agent 1/2/3 与后处理消费同一份快照。
    **装配后不再修改 memory_summary / memory_confidence / memory_answer：**
    Agent 1 与 Agent 3 按需从同一 ``memory_answer`` 渲染不同 profile，
    或读取 ``drive_result.context_summary`` 作为评估后摘要，避免同一字段
    在不同阶段被改写后语义漂移。
    """
    # WS-1: 身份（引用，不拷贝）
    personality_name: str
    # WS-2: 情绪：轮次开始的快照（dict，来自 EmotionalState.to_prompt_summary()）
    emotion_summary: dict
    # WS-3: 关系四维
    relationship: dict
    # WS-4: 记忆：Agent 1 检索一次产出的摘要文本（context_summary），
    # 及 memory_agent 置信度（未走 memory_agent 时为 None）
    memory_summary: str = ""
    memory_confidence: float | None = None
    # WS-5: 原始记忆检索结果（MemoryAnswer 或 None），用于按不同 profile
    # 渲染给 Agent 1/3，避免同一份证据被重复检索或格式失真。
    memory_answer: object | None = None
    # WS-6: 挂念清单浮现（可为空；当前由 context_summary 透传）
    care_surface: list[str] = field(default_factory=list)
    # WS-7: 决策槽：Agent 1 决策后写入（needs_tools/summary）
    pending: dict = field(default_factory=dict)
    # WS-8: 元信息
    turn_count: int = 0
    idle_seconds: float = 0.0
    is_sleeping: bool = False


class MemoryContextProvider:
    """Builds memory/relationship summaries once per user message.

    2026-07-22 自 core/memory_context_provider.py 并入（同域归并：
    检索策略（memory_agent / retriever / 空 query 分流 + 同消息 memo）
    与格式化（关系块+记忆块），即填进 CognitiveState.memory_summary 的那份内容。
    """

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
                _logger.warning(f"[inner_drive] memory agent failed, retriever fallback: {e}")
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
                _logger.debug(f"[inner_drive] context via memory agent "
                              f"(confidence={ma.confidence})")
                return full
            _logger.debug("[inner_drive] memory agent empty, retriever fallback")
        return self.build_summary(self._retriever.retrieve_for_query(user_input))

    @staticmethod
    def format_memory_answer(ma) -> str:
        """Thin wrapper around ContextBuilder for backward compatibility.
        Agent 1 receives the full memory context with confidence markers."""
        from memory.retrieval_pipeline import ContextBuilder
        return ContextBuilder().build("agent1", ma)


def render_memory_light(memory_answer, fallback: str = "") -> str:
    """Render a MemoryAnswer with the Agent 3 light profile.

    Returns ``fallback`` when ``memory_answer`` is None or the light profile
    renders to an empty string. Used by Agent 1 and Agent 3 to share the same
    lightweight memory view without duplicating fallback logic.
    """
    if memory_answer is None:
        return fallback
    from memory.retrieval_pipeline import ContextBuilder
    light = ContextBuilder().build("agent3", memory_answer)
    return light if light else fallback
