#!/usr/bin/env python3
"""AI Friend — Web 端启动入口。"""

import logging

import uvicorn

from config import load_config
from core.logging_setup import setup_logging


def main():
    config = load_config()
    setup_logging(config.log_level)

    host = getattr(config, 'web_host', '0.0.0.0')
    port = getattr(config, 'web_port', 8000)

    logger = logging.getLogger(__name__)
    logger.info(f"Starting AI Friend Web: model={config.api_model} host={host}:{port} log_level={config.log_level}")

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
