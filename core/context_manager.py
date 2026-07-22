"""Context window management: token estimation + compression."""

import logging
from functools import lru_cache

from memory.short_term import ConversationBuffer

_MODEL_CONTEXT = 1_000_000  # deepseek-v4-flash: 1M tokens
COMPRESS_THRESHOLD = int(_MODEL_CONTEXT * 0.8)

_TOKENIZER = None
_TOKENIZER_ENCODING = "cl100k_base"

logger = logging.getLogger(__name__)


def _get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            import tiktoken
            _TOKENIZER = tiktoken.get_encoding(_TOKENIZER_ENCODING)
        except (ImportError, Exception):
            _TOKENIZER = False
    return _TOKENIZER


def _estimate_tokens_impl(text: str) -> int:
    """Actual token estimation logic (without empty guard)."""
    tok = _get_tokenizer()
    if tok:
        return len(tok.encode(text, disallowed_special=()))
    # #262: 补 CJK Ext A (U+3400-U+4DBF)；本分支仅在 tiktoken 不可用时生效
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿' or '\U00020000' <= c <= '\U0002A6DF' or '　' <= c <= '〿')
    ascii_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    other = len(text) - cjk - ascii_chars - digits
    return max(1, int(cjk * 1.5 + ascii_chars / 4 + digits / 3 + other / 8))


@lru_cache(maxsize=2048)
def _estimate_tokens_cached(text: str) -> int:
    """Cached token estimation. T2: LRU cache for short-to-medium texts."""
    return _estimate_tokens_impl(text)


def estimate_tokens(text: str) -> int:
    """Estimate token count with LRU cache. T2: short texts cached, long texts bypass."""
    if not text:
        return 0
    # 超长文本不缓存（避免单条大文本顶掉整个缓存）
    if len(text) > 4000:
        return _estimate_tokens_impl(text)
    return _estimate_tokens_cached(text)


# T3: 压缩排版常数
RECENT_FULL_TURNS = 6        # 最近 6 条完整保留
OLDER_SNIPPET = 120          # 更早的每条截断到 120 字符
MAX_COMPRESS_INPUT = 12000   # 压缩输入总字符预算（原 8000 上调）


class ContextManager:
    """Manages LLM context window: token tracking + compression + summary storage."""

    def __init__(self, provider, short_term: ConversationBuffer):
        self._provider = provider
        self._short_term = short_term
        self._compressed_summary: str = ""
        self._estimated_tokens_used: int = 0
        self._compressing: bool = False

    @property
    def compressed_summary(self) -> str:
        return self._compressed_summary

    @property
    def estimated_tokens(self) -> int:
        return self._estimated_tokens_used

    def should_compress(self, estimated_tokens: int) -> bool:
        """T1: #295 — 由本模块统一判断是否需要压缩（此前阈值判断散在调用方）。"""
        return estimated_tokens >= COMPRESS_THRESHOLD

    def reset_estimate(self, count: int) -> None:
        self._estimated_tokens_used = count

    def add_estimate(self, tokens: int) -> None:
        self._estimated_tokens_used += tokens

    def compress(self, messages: list[dict]) -> None:
        """Public entry point — thin wrapper with recursion guard."""
        if self._compressing:
            return
        self._compressing = True
        try:
            self._do_compress(messages)
        finally:
            self._compressing = False

    def _do_compress(self, messages: list[dict]) -> None:
        """T3+T4: 最近 K 条完整保留+更早的短截断+增量摘要合并（此前均匀截断+全量覆盖）。"""
        from prompts.system import CONTEXT_COMPRESS_PROMPT

        non_system = [m for m in messages if m["role"] != "system"]
        if not non_system:
            return

        recent = non_system[-RECENT_FULL_TURNS:]
        older = non_system[:-RECENT_FULL_TURNS] if len(non_system) > RECENT_FULL_TURNS else []

        parts = []
        for m in older:
            content = m["content"][:OLDER_SNIPPET]
            parts.append(f"{'用户' if m['role'] == 'user' else '你'}: {content}")
        for m in recent:
            parts.append(f"{'用户' if m['role'] == 'user' else '你'}: {m['content']}")
        text = "\n".join(parts)
        if not text.strip():
            return
        if len(text) > MAX_COMPRESS_INPUT:
            text = text[-MAX_COMPRESS_INPUT:]

        # T4: 有旧摘要时增量合并，保留早期信息
        if self._compressed_summary:
            compress_input = (f"【已有历史摘要】\n{self._compressed_summary}"
                              f"\n\n【新增对话】\n{text}")
        else:
            compress_input = text

        try:
            result = self._provider.generate(
                [{"role": "user", "content": CONTEXT_COMPRESS_PROMPT.format(conversation=compress_input)}],
                stream=False, source="context_compress",
            )
            if result.strip():
                self._compressed_summary = result.strip()
                self._estimated_tokens_used = 0
                self._short_term.clear()
                logger.info(f"Context compressed: {self._compressed_summary[:80]}")
        except Exception as e:
            logger.warning(f"Compression failed: {e}")
