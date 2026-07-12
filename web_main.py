#!/usr/bin/env python3
"""AI Friend — Web 端启动入口。"""

import logging
import sys

import uvicorn

from config import load_config
from core.embedding_server import auto_start_embedding
from core.logging_setup import setup_logging


def main():
    try:
        config = load_config()
        setup_logging(config.log_level)
        logger = logging.getLogger(__name__)
        auto_start_embedding(logger)

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
    except Exception as e:
        logging.getLogger(__name__).critical(f"Failed to start: {e}")
        print(f"\n[错误] 启动失败: {e}")
        print("请检查 config.json 配置是否正确。")
        sys.exit(1)


if __name__ == "__main__":
    main()
