"""Embedding server lifecycle helpers (shared between CLI and Web entrypoints)."""

import logging
import os
import subprocess
import time
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_ENDPOINT = "http://localhost:8080/v1/embeddings"


def kill_existing_llama() -> None:
    """Kill any existing llama-server processes before starting a new one."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        if "llama-server.exe" in result.stdout:
            subprocess.run(
                ["taskkill", "/F", "/IM", "llama-server.exe"],
                capture_output=True, timeout=5,
            )
            logger.info("[embed] killed existing llama-server process")
    except Exception:
        pass


def auto_start_embedding(logger_ref: logging.Logger | None = None,
                         endpoint: str = DEFAULT_EMBEDDING_ENDPOINT) -> None:
    """Start embedding server if not running. Non-blocking after launch."""
    log = logger_ref or logger
    try:
        resp = urllib.request.urlopen(endpoint, timeout=2)
        resp.read()
        log.info("[embed] server already running")
        return
    except Exception:
        pass

    # Kill stale llama process before starting fresh
    kill_existing_llama()

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model = os.path.join(project, "memory", "Qwen3.5-0.8B-Q6_K.gguf")
    if not os.path.exists(model):
        log.info("[embed] model not found, skipping auto-start")
        return

    log.info("[embed] starting embedding server...")
    try:
        # Use start_embedding_server.bat to avoid Chinese path encoding issues
        bat_path = os.path.join(project, "start_embedding_server.bat")
        if os.path.exists(bat_path):
            subprocess.Popen(
                [bat_path],
                cwd=project,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # Fallback: relative paths from project directory
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
                log.info(f"[embed] server ready ({i+1}s)")
                return
            except Exception:
                continue
        log.warning("[embed] server did not respond within 30s, falling back to keyword search")
    except Exception as e:
        log.warning(f"[embed] failed to start: {e}")
