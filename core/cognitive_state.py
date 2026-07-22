"""每轮消息的统一运行时状态（World State / Blackboard 雏形）。

每轮用户输入装配一次，Agent 1/2/3 与后处理消费同一份，
不再各自重新检索/理解（Think Once, Use Everywhere）。
"""
from dataclasses import dataclass, field


@dataclass
class CognitiveState:
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
