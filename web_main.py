#!/usr/bin/env python3
"""AI Friend — Web 端启动入口。"""

import logging
import sys

import uvicorn

from core.embedding_server import auto_start_embedding
from core.logging_setup import setup_logging


def main():
    try:
        # M-19: 先以 INFO 初始化日志再加载配置，避免丢失 load_config 的启动日志
        setup_logging("INFO")
        # L-10/L-12: 复用 web.server 模块级 config（全进程单例），不再重复 load_config；
        # 导入即触发其唯一的模块级 load_config()，此时日志已就绪
        from web.server import config
        setup_logging(config.log_level)
        logger = logging.getLogger(__name__)
        # H-04: 传入配置的 embedding endpoint，自动启动端口与引擎连接端口保持一致
        auto_start_embedding(logger, config.embedding_endpoint)

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
