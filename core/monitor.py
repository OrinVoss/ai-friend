"""LLM API 调用监控缓冲。记录每次 generate() 的完整请求/响应。

开发调试用，记录每次发往 DeepSeek 的完整消息和返回。
默认最多保留 200 条（环形缓冲），避免长期运行内存无限增长。
可通过 max_size 参数调整；设为 0 则不限制。
"""
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

DEFAULT_MONITOR_SIZE = 200


@dataclass
class MonitorRecord:
    """一次 LLM API 调用的完整记录，无任何截断。"""
    timestamp: str = ""
    model: str = ""
    duration_ms: float = 0.0
    max_tokens: int = 0
    temperature: float = 0.0
    response_format: dict | None = None
    messages: list = field(default_factory=list)      # 完整 messages（含 system/user/assistant）
    response: str = ""                                 # 完整响应文本
    source: str = ""                                   # "assess" / "review" / "re_decide" / "tool_agent" / "react" / "dream"


class MonitorBuffer:
    """线程安全的环形缓冲，保留最近 N 条 API 调用记录。"""

    def __init__(self, max_size: int = DEFAULT_MONITOR_SIZE):
        self._max_size = max_size
        self._buffer: deque[MonitorRecord] = deque(maxlen=max_size if max_size > 0 else None)
        self._lock = threading.Lock()

    @property
    def max_size(self) -> int:
        return self._max_size

    @max_size.setter
    def max_size(self, value: int):
        with self._lock:
            self._max_size = value
            # Rebuild deque with new maxlen
            new_max = value if value > 0 else None
            old_items = list(self._buffer)
            self._buffer = deque(old_items[-value:] if value > 0 else old_items, maxlen=new_max)

    def record(self, rec: MonitorRecord):
        with self._lock:
            self._buffer.append(rec)

    def get_all(self, limit: int = 0) -> list[dict]:
        """返回记录。limit=0 返回全部，>0 返回最近 N 条（均已按时间倒序）。"""
        with self._lock:
            items = list(self._buffer)
        if limit > 0 and len(items) > limit:
            items = items[-limit:]
        items.reverse()
        return [asdict(r) for r in items]

    def clear(self):
        with self._lock:
            self._buffer.clear()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._buffer)

    def is_enabled(self, cfg=None) -> bool:
        """根据配置判断是否启用监控记录。"""
        if cfg is None:
            return True
        return getattr(cfg, "monitor_enabled", True)


# 全局单例
_monitor = MonitorBuffer()
_monitor_enabled = True


def get_monitor() -> MonitorBuffer:
    return _monitor


def set_monitor_enabled(enabled: bool):
    """全局开关：是否继续记录新的 LLM 调用。"""
    global _monitor_enabled
    _monitor_enabled = enabled


def is_monitor_enabled() -> bool:
    return _monitor_enabled


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
    """记录一次完整的 LLM API 调用（若监控被禁用则忽略）。"""
    if not _monitor_enabled:
        return
    rec = MonitorRecord(
        timestamp=time.strftime("%H:%M:%S"),
        model=model,
        duration_ms=round(duration_ms, 1),
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
        messages=messages,
        response=response,
        source=source,
    )
    _monitor.record(rec)
