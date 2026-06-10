#!/usr/bin/env python3
"""AI Friend — Web 端启动入口。"""

import logging
import os
import subprocess
import time

import uvicorn

from config import load_config
from core.logging_setup import setup_logging


def _auto_start_embedding(logger, endpoint="http://localhost:8080/v1/embeddings"):
    """Start embedding server if not running. Non-blocking after launch."""
    import urllib.request
    try:
        resp = urllib.request.urlopen(endpoint, timeout=2)
        resp.read()
        logger.info("[embed] server already running")
        return
    except Exception:
        pass

    project = os.path.dirname(os.path.abspath(__file__))
    llama_server = os.path.join(project, "memory", "llama-bin", "llama-server.exe")
    model = os.path.join(project, "memory", "Qwen3.5-0.8B-Q6_K.gguf")
    if not os.path.exists(llama_server) or not os.path.exists(model):
        logger.info("[embed] binary or model not found, skipping auto-start")
        return

    logger.info("[embed] starting embedding server...")
    try:
        subprocess.Popen(
            [llama_server, "-m", model, "--embeddings", "--port", "8080",
             "-ngl", "99", "--ctx-size", "2048", "--batch-size", "512",
             "--threads", "4", "--host", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for i in range(10):
            time.sleep(1)
            try:
                resp = urllib.request.urlopen(endpoint, timeout=1)
                resp.read()
                logger.info(f"[embed] server ready ({i+1}s)")
                return
            except Exception:
                continue
        logger.warning("[embed] server did not respond within 10s, falling back to keyword search")
    except Exception as e:
        logger.warning(f"[embed] failed to start: {e}")


def main():
    config = load_config()
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)
    _auto_start_embedding(logger)

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
