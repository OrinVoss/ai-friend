"""Shared logging setup — writes to logs/YYYY-MM-DD.log + stderr.

A3（2026-07-21，logging.md P1-4/P1-6）：请求级 request_id——
ContextVar + logging.Filter 注入每条 record，formatter 带 %(request_id)s
（为空显示 '-'，不破坏现有行格式）。独处/睡眠循环的日志天然显示 '-'，
与请求驱动日志自然区分。
"""

import contextvars
import logging
import os
import sys
import uuid
from datetime import datetime

# 模块级单例：web 中间件 / message_handler 设置，Filter/monitor 读取
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="")


def new_request_id() -> str:
    """生成短请求 ID（uuid4 前 8 位）。"""
    return uuid.uuid4().hex[:8]


class RequestIdFilter(logging.Filter):
    """把当前 ContextVar 的 request_id 注入 record（空 → '-'）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def setup_logging(level: str = "INFO") -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"{today}.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers before adding new ones (prevent duplicates on re-setup)
    root.handlers.clear()

    # File handler — full timestamp
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(RequestIdFilter())
    root.addHandler(fh)

    # Console handler — time-only timestamp
    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
        datefmt="%H:%M:%S",
    )
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(console_fmt)
    ch.addFilter(RequestIdFilter())
    root.addHandler(ch)


class _PromptToolkitHandler(logging.Handler):
    """CLI 交互模式的控制台输出：经 print_formatted_text 打到输入行上方。

    直接写 stderr 会把 prompt_toolkit 的输入行/状态栏冲花（2026-08-18 用户
    反馈日志与聊天混在一起）；仅承载 WARNING+，完整日志始终在 logs/ 文件。
    """

    _COLORS = {
        logging.WARNING: "\x1b[33m",
        logging.ERROR: "\x1b[31m",
        logging.CRITICAL: "\x1b[1;31m",
    }

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from prompt_toolkit import print_formatted_text
            from prompt_toolkit.formatted_text import ANSI
            color = self._COLORS.get(record.levelno, "\x1b[33m")
            print_formatted_text(ANSI(f"{color}{self.format(record)}\x1b[0m"))
        except Exception:
            pass  # 日志永远不弄挂应用


def use_prompt_toolkit_console(level: str = "WARNING") -> None:
    """把 stderr 控制台 handler 换成 prompt_toolkit 感知版（CLI 聊天期间）。

    仅替换控制台 handler；文件 handler 不受影响（完整日志照写）。
    非交互环境（session 创建失败/管道）不应调用。
    """
    if not isinstance(level, str):  # 防御：MagicMock/None 等非法值回退默认
        level = "WARNING"
    root = logging.getLogger()
    for h in list(root.handlers):
        # FileHandler 是 StreamHandler 子类，必须显式排除
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            root.removeHandler(h)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = _PromptToolkitHandler()
    handler.setFormatter(fmt)
    handler.setLevel(getattr(logging, level.upper(), logging.WARNING))
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
