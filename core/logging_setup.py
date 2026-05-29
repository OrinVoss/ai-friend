"""Shared logging setup — writes to logs/YYYY-MM-DD.log + stderr."""

import logging
import os
import sys
from datetime import datetime


def setup_logging(level: str = "INFO") -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"{today}.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # File handler — full timestamp
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler — time-only timestamp
    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(console_fmt)
    root.addHandler(ch)
