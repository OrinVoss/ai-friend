#!/usr/bin/env python3
"""AI Friend — Web 端启动入口。"""

import logging
import sys

import uvicorn

from config import load_config


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main():
    config = load_config()
    setup_logging(config.log_level)

    host = getattr(config, 'web_host', '0.0.0.0')
    port = getattr(config, 'web_port', 8000)

    print(f"  AI Friend - {config.api_model}")
    print(f"  Web: http://localhost:{port}")
    print()

    uvicorn.run(
        "web.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
