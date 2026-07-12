#!/usr/bin/env python3
"""AI Friend — Web 端启动入口。"""

import logging
import os
import subprocess
import time

import uvicorn

from config import load_config
from core.logging_setup import setup_logging


def _kill_existing_llama(logger):
    """Kill any existing llama-server processes before starting a new one."""
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        if "llama-server.exe" in result.stdout:
            subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                          capture_output=True, timeout=5)
            logger.info("[embed] killed existing llama-server process")
    except Exception:
        pass


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

    # Kill stale llama process before starting fresh
    _kill_existing_llama(logger)

    project = os.path.dirname(os.path.abspath(__file__))
    model = os.path.join(project, "memory", "Qwen3.5-0.8B-Q6_K.gguf")
    if not os.path.exists(model):
        logger.info("[embed] model not found, skipping auto-start")
        return

    logger.info("[embed] starting embedding server...")
    try:
        bat_path = os.path.join(project, "start_embedding_server.bat")
        if os.path.exists(bat_path):
            subprocess.Popen(
                [bat_path],
                cwd=project,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [os.path.join("memory", "llama-bin", "llama-server.exe"),
                 "-m", os.path.join("memory", "Qwen3.5-0.8B-Q6_K.gguf"),
                 "--embeddings", "--port", "8080",
                 "-ngl", "99", "--ctx-size", "2048", "--batch-size", "512",
                 "--threads", "4", "--host", "127.0.0.1"],
                cwd=project,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        for i in range(30):  # 640MB model may take 15-30s to load
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
    try:
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
    except Exception as e:
        logging.getLogger(__name__).critical(f"Failed to start: {e}")
        print(f"\n[错误] 启动失败: {e}")
        print("请检查 config.json 配置是否正确。")
        sys.exit(1)


if __name__ == "__main__":
    main()
