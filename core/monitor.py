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


@dataclass
class ToolMetrics:
    """Per-tool aggregated metrics."""
    calls: int = 0
    successes: int = 0
    failures: int = 0
    retries: int = 0
    total_elapsed_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.calls == 0:
            return 0.0
        return self.successes / self.calls

    @property
    def avg_elapsed_ms(self) -> float:
        if self.calls == 0:
            return 0.0
        return self.total_elapsed_ms / self.calls

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "retries": self.retries,
            "success_rate": round(self.success_rate, 4),
            "avg_elapsed_ms": round(self.avg_elapsed_ms, 2),
        }


class ToolMetricsCollector:
    """Thread-safe collector for per-tool success / latency / retry metrics."""

    def __init__(self):
        self._data: dict[str, ToolMetrics] = {}
        self._lock = threading.Lock()

    def record(self, name: str, success: bool, elapsed_ms: float, retries: int = 0):
        with self._lock:
            metrics = self._data.setdefault(name, ToolMetrics())
            metrics.calls += 1
            if success:
                metrics.successes += 1
            else:
                metrics.failures += 1
            metrics.retries += retries
            metrics.total_elapsed_ms += elapsed_ms

    def get_all(self) -> dict[str, ToolMetrics]:
        with self._lock:
            return {k: ToolMetrics(
                calls=v.calls,
                successes=v.successes,
                failures=v.failures,
                retries=v.retries,
                total_elapsed_ms=v.total_elapsed_ms,
            ) for k, v in self._data.items()}

    def clear(self):
        with self._lock:
            self._data.clear()


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
_tool_metrics = ToolMetricsCollector()


def get_monitor() -> MonitorBuffer:
    return _monitor


def get_tool_metrics() -> dict[str, dict]:
    """Return per-tool metrics suitable for the web panel."""
    return {k: v.to_dict() for k, v in _tool_metrics.get_all().items()}


def record_tool_metric(name: str, success: bool, elapsed_ms: float, retries: int = 0):
    """Record a single tool invocation metric."""
    _tool_metrics.record(name, success, elapsed_ms, retries=retries)


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
