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


class HistorySearchTool(Tool):
    """Search original conversation history — keyword LIKE, semantic vector, or batch range read.

    T3: history after M-03 unify memory (2026-07-22): this is the channel for
    raw-turn retrieval when the char-budget in _build_messages has dropped older
    turns from the prompt.
    """

    ALIASES = {
        "query": ("search", "keyword"),
        "turn_number": ("turn", "from_turn", "start"),
    }

    is_internal = True
    timeout_seconds = 15.0

    def __init__(self, retriever, ltm):
        self.retriever = retriever
        self.ltm = ltm
        self._embed_cache = None  # {turn_number: np.ndarray}, lazy init

    def name(self) -> str:
        return "history_search"

    def description(self) -> str:
        return (
            "搜索原始对话历史。用一两个关键词精准搜索，如'摄影'、'歌名'；"
            "想语义模糊查找用 mode=semantic；按 turn_number 批量读整段上下文。"
            "recall 查提炼记忆（facts/experiences/insights），"
            "history_search 查原始对话。"
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词（一两个词即可，不用整句）",
                },
                "mode": {
                    "type": "string",
                    "enum": ["keyword", "semantic"],
                    "description": "搜索模式：keyword=精确匹配（默认），semantic=向量语义",
                },
                "turn_number": {
                    "type": "integer",
                    "description": "按轮次起始号批量读一段对话（给了此参数忽略 query/mode）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认6，上限15",
                },
            },
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            query = (args.get("query") or "").strip()
            mode = (args.get("mode") or "keyword").strip().lower()
            turn_number = int(args.get("turn_number") or 0)
            limit = min(int(args.get("limit") or 6), 15)

            # Batch mode: read by turn range
            if turn_number > 0:
                return self._batch_read(turn_number, limit)

            # No query → latest N turns
            if not query:
                return self._batch_read(0, limit)

            # Keyword or semantic search
            if mode == "semantic":
                result = self._semantic_search(query, limit)
                if result is not None:
                    return result
                # Semantic failed — fall through to keyword
                logger.info("[tool] history_search semantic failed, keyword fallback")

            # Keyword (LIKE) search
            return self._keyword_search(query, limit)

        except Exception as e:
            logger.exception(f"[tool] history_search failed: {e}")
            return ToolResult.fail(
                f"搜索对话失败: {e}",
                error_type=ERROR_TYPE_INTERNAL,
                retryable=False,
            )

    def _format_turns(self, turns: list[dict]) -> str:
        """Format turns for output with char limits."""
        parts = []
        total_chars = 0
        for t in turns:
            role = "用户" if t.get("role") == "user" else "你"
            tn = t.get("turn_number", "?")
            created = t.get("created_at", "")
            content = (t.get("content") or "")[:200]
            line = f"[#{tn}] {role} ({created}): {content}"
            if total_chars + len(line) > 1500:
                break
            parts.append(line)
            total_chars += len(line)
        return "\n".join(parts)

    def _keyword_search(self, query: str, limit: int) -> ToolResult:
        turns = self.ltm.search_turns(query, limit=limit)
        if not turns:
            return ToolResult.ok("没找到相关对话")
        return ToolResult.ok(self._format_turns(turns))

    def _semantic_search(self, query: str, limit: int) -> ToolResult | None:
        """Semantic search. Returns None when embedding unavailable (caller falls back)."""
        embed = self.retriever.embedding_engine
        if not embed or not embed.health_check():
            return None

        try:
            import numpy as np
        except ImportError:
            return None

        # Get recent 200 turns from DB
        recent = self.ltm.repo.get_recent_turns_sync(limit=200)

        # Init cache lazily
        if self._embed_cache is None:
            self._embed_cache = {}

        # Encode new turns only
        for t in recent:
            tn = t.get("turn_number")
            if tn is None or tn in self._embed_cache:
                continue
            try:
                vec = embed.encode_single(t.get("content", ""))
                self._embed_cache[tn] = vec
            except Exception:
                continue

        # Encode query
        try:
            query_vec = embed.encode_single(query)
        except Exception:
            return None

        # Score by cosine similarity
        scored = []
        for t in recent:
            tn = t.get("turn_number")
            vec = self._embed_cache.get(tn)
            if vec is None:
                continue
            sim = float(np.dot(vec, query_vec))
            if sim >= 0.5:
                scored.append((t, sim))

        if not scored:
            return ToolResult.ok("没找到相关对话")

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [t for t, _ in scored[:limit]]
        return ToolResult.ok(self._format_turns(results))

    def _batch_read(self, turn_number: int, count: int) -> ToolResult:
        turns = self.ltm.get_turns_range(turn_number, count)
        if not turns:
            return ToolResult.ok("没找到相关对话")
        return ToolResult.ok(self._format_turns(turns))
