"""Tool implementations for memory operations: recall and remember."""

import logging
from typing import Any

from tools.traits import (
    Tool, ToolResult,
    ERROR_TYPE_PARAM_ERROR, ERROR_TYPE_INTERNAL,
)
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever

logger = logging.getLogger(__name__)


class RecallTool(Tool):
    """Recall past memories about the user or shared experiences."""

    # KI-1: 本工具自己的参数别名（原 dispatcher 全局别名下沉）
    ALIASES = {"query": ("search", "keyword", "question")}

    is_internal = True
    timeout_seconds = 10.0

    def __init__(self, retriever: MemoryRetriever, ltm: LongTermMemory):
        self.retriever = retriever
        self.ltm = ltm

    def name(self) -> str:
        return "recall"

    def description(self) -> str:
        return "回忆关于用户的信息或你们之前的共同经历。用自然语言描述你想回忆的内容。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "你想回忆什么？用自然语言描述关键词即可",
                }
            },
            "required": ["query"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            query = args.get("query", "").strip()
            if not query:
                return ToolResult.fail(
                    "请告诉我你想回忆什么",
                    error_type=ERROR_TYPE_PARAM_ERROR,
                    retryable=False,
                )

            logger.info(f"[tool] recall query={query[:60]}")
            # 修复：recall 不再用 ltm.search_facts（整句 LIKE 恒 0 命中），
            # 改走 retriever 混合检索管线（语义 0.6 + 关键词 0.4，
            # embedding 宕机时自动降级关键词评分）——Agent 1/3 的 recall
            # 与 memory context 检索同源。
            ctx = self.retriever.retrieve_for_query(query)
            facts = ctx.facts[:5]
            experiences = ctx.experiences[:3]
            reflections = ctx.reflections[:2]
            logger.info(f"[tool] recall result: facts={len(facts)} exps={len(experiences)} refl={len(reflections)}")

            parts = []

            if facts:
                parts.append("关于用户我知道：")
                for f in facts:
                    parts.append(f"- {f.fact_key}: {f.fact_value}")

            if experiences:
                parts.append("共同回忆：")
                for e in experiences:
                    # F4: 梦境标记，防止被当作真实事件
                    dream_prefix = "【梦境，非真实事件】" if ("dream" in (getattr(e, "tags", None) or [])) else ""
                    parts.append(f"- {dream_prefix}[{e.emotional_tone}] {e.summary}")

            if reflections:
                parts.append("相关思考：")
                for r in reflections:
                    parts.append(f"- {r.content}")

            if not parts:
                return ToolResult.ok(f"没有找到关于「{query}」的记忆")

            return ToolResult.ok("\n".join(parts))
        except Exception as e:
            logger.exception(f"[tool] recall failed: {e}")
            return ToolResult.fail(
                f"回忆失败: {e}",
                error_type=ERROR_TYPE_INTERNAL,
                retryable=False,
            )


class RememberTool(Tool):
    """Explicitly remember an important fact about the user."""

    is_internal = True
    timeout_seconds = 10.0

    def __init__(self, ltm: LongTermMemory):
        self.ltm = ltm

    def name(self) -> str:
        return "remember"

    def description(self) -> str:
        return "主动记住一条关于用户的重要信息，以后可以回忆起来。当你听到用户的重要个人信息、偏好、经历时使用。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["preference", "identity", "event", "relationship", "routine"],
                    "description": "信息类别",
                },
                "key": {
                    "type": "string",
                    "description": "关键词（如'最喜欢的食物'）",
                },
                "value": {
                    "type": "string",
                    "description": "具体内容（如'意大利面'）",
                },
                "importance": {
                    "type": "number",
                    "description": "重要性 0~1",
                    "default": 0.6,
                },
                "correct": {
                    "type": "boolean",
                    "description": "纠正之前记住的错误信息",
                    "default": False,
                },
                "fact_type": {
                    "type": "string",
                    "enum": ["user_fact", "agent_fact", "system_fact"],
                    "description": "事实主体类型（#127），默认 user_fact",
                    "default": "user_fact",
                },
            },
            "required": ["category", "key", "value"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            category = args.get("category", "preference")
            key = args.get("key", "").strip()
            value = args.get("value", "").strip()
            importance = float(args.get("importance", 0.6))
            is_correction = args.get("correct", False)
            fact_type = args.get("fact_type", "user_fact")  # #127

            if not key or not value:
                return ToolResult.fail(
                    "请提供关键词和具体内容",
                    error_type=ERROR_TYPE_PARAM_ERROR,
                    retryable=False,
                )

            if is_correction:
                similar = self.ltm.search_facts(key, limit=5)
                old_id = None
                for f in similar:
                    if f.category == category and f.fact_key == key:
                        old_id = f.id
                        break
                self.ltm.correct_fact(category, key, value, old_fact_id=old_id)
                logger.info(f"Corrected fact: {category}/{key} = {value}")
                return ToolResult.ok(f"已纠正: {key} = {value}")
            else:
                self.ltm.store_fact(category, key, value, confidence=0.9,
                                   importance=importance, fact_type=fact_type)
                logger.info(f"Remembered: {category}/{key} = {value} type={fact_type}")
                return ToolResult.ok(f"已记住: {key} = {value}")
        except Exception as e:
            logger.exception(f"[tool] remember failed: {e}")
            return ToolResult.fail(
                f"记忆失败: {e}",
                error_type=ERROR_TYPE_INTERNAL,
                retryable=False,
            )
