"""Tool implementations for memory operations: recall and remember."""

import logging
from typing import Any

from tools.traits import Tool, ToolResult
from memory.long_term import LongTermMemory
from memory.retrieval import MemoryRetriever

logger = logging.getLogger(__name__)


class RecallTool(Tool):
    """Recall past memories about the user or shared experiences."""

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
        query = args.get("query", "").strip()
        if not query:
            return ToolResult.fail("请告诉我你想回忆什么")

        logger.info(f"[tool] recall query={query[:60]}")
        keywords = self.retriever._extract_keywords(query)
        facts = self.ltm.search_facts(query, limit=5)
        experiences = self.ltm.search_experiences(keywords, limit=3)
        reflections = self.ltm.get_recent_reflections(limit=2)
        logger.info(f"[tool] recall result: facts={len(facts)} exps={len(experiences)} refl={len(reflections)}")

        parts = []

        if facts:
            parts.append("关于用户我知道：")
            for f in facts:
                parts.append(f"- {f.fact_key}: {f.fact_value}")

        if experiences:
            parts.append("共同回忆：")
            for e in experiences:
                parts.append(f"- [{e.emotional_tone}] {e.summary}")

        if reflections:
            parts.append("相关思考：")
            for r in reflections:
                parts.append(f"- {r.content}")

        if not parts:
            return ToolResult.ok(f"没有找到关于「{query}」的记忆")

        return ToolResult.ok("\n".join(parts))


class RememberTool(Tool):
    """Explicitly remember an important fact about the user."""

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
                    "description": "重要性 0~1，0.3以下=临时 0.6=长期 1.0=永久（默认0.6）",
                    "default": 0.6,
                },
            },
            "required": ["category", "key", "value"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        category = args.get("category", "preference")
        key = args.get("key", "").strip()
        value = args.get("value", "").strip()
        importance = float(args.get("importance", 0.6))

        if not key or not value:
            return ToolResult.fail("请提供关键词和具体内容")

        self.ltm.store_fact(category, key, value, confidence=0.9, importance=importance)
        logger.info(f"Remembered: {category}/{key} = {value} (imp={importance})")
        return ToolResult.ok(f"已记住: {key} = {value}")
