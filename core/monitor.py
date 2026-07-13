"""LLM API 调用监控缓冲。记录每次 generate() 的请求/响应。"""
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class MonitorRecord:
    """一次 LLM API 调用的完整记录。"""
    timestamp: str = ""
    model: str = ""
    duration_ms: float = 0.0
    max_tokens: int = 0
    temperature: float = 0.0
    response_format: dict | None = None
    # 消息（仅保留摘要，避免 OOM）
    system_msg_preview: str = ""  # system 消息前 200 字
    user_msg_preview: str = ""   # 最后一条 user 消息前 200 字
    full_messages_count: int = 0
    full_messages_chars: int = 0
    # 响应
    response_preview: str = ""   # 前 500 字
    full_response: str = ""      # 完整响应（limit 5000）
    # 来源标记
    source: str = ""             # "assess" / "review" / "re_decide" / "proactive" / "tool_agent" / "react" / "dream" / etc.


class MonitorBuffer:
    """线程安全的环形缓冲，保留最近 N 条 API 调用记录。"""

    def __init__(self, maxlen: int = 200):
        self._buffer: deque[MonitorRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, rec: MonitorRecord):
        with self._lock:
            self._buffer.appendleft(rec)

    def get_all(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [asdict(r) for r in list(self._buffer)[:limit]]

    def clear(self):
        with self._lock:
            self._buffer.clear()


# 全局单例
_monitor = MonitorBuffer()


def get_monitor() -> MonitorBuffer:
    return _monitor


def record_call(
    model: str,
    messages: list[dict],
    response: str,
    duration_ms: float,
    max_tokens: int = 0,
    temperature: float = 0.0,
    response_format: dict | None = None,
    source: str = "",
) -> None:
    """便捷函数：记录一次 API 调用。"""
    rec = MonitorRecord(
        timestamp=time.strftime("%H:%M:%S"),
        model=model,
        duration_ms=round(duration_ms, 1),
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
        full_messages_count=len(messages),
        full_messages_chars=sum(len(m.get("content", "")) for m in messages),
        full_response=response[:5000],
        source=source,
    )
    # 提取 system 消息预览
    for m in messages:
        if m.get("role") == "system" and m.get("content"):
            rec.system_msg_preview = m["content"][:200]
            break
    # 提取最后一条 user 消息预览
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            rec.user_msg_preview = m["content"][:200]
            break
    # response 预览
    rec.response_preview = response[:500]
    _monitor.record(rec)
    logger.debug(f"[monitor] recorded: {source} {model} {duration_ms:.0f}ms")
