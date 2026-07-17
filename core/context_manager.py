"""Context window management: token estimation + compression."""

import logging

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


def estimate_tokens(text: str) -> int:
    tok = _get_tokenizer()
    if tok:
        return len(tok.encode(text, disallowed_special=()))
    # #262: 补 CJK Ext A (U+3400-U+4DBF)；本分支仅在 tiktoken 不可用时生效
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿' or '\U00020000' <= c <= '\U0002A6DF' or '　' <= c <= '〿')
    ascii_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    other = len(text) - cjk - ascii_chars - digits
    return max(1, int(cjk * 1.5 + ascii_chars / 4 + digits / 3 + other / 8))


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
            result = self._provider.generate(
                [{"role": "user", "content": CONTEXT_COMPRESS_PROMPT.format(conversation=text)}],
                stream=False, source="context_compress",
            )
            if result.strip():
                self._compressed_summary = result.strip()
                self._estimated_tokens_used = 0
                self._short_term.clear()
                logger.info(f"Context compressed: {self._compressed_summary[:80]}")
        except Exception as e:
            logger.warning(f"Compression failed: {e}")
