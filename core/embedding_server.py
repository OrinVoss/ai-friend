"""Embedding server lifecycle helpers (shared between CLI and Web entrypoints)."""

import logging
import os
import subprocess
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_ENDPOINT = "http://localhost:8080/v1/embeddings"
MAX_WAIT_SECONDS = 90          # ES-001: give slower machines more time to load the model
WAIT_POLL_INTERVAL = 1


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
            # Give Windows a moment to release the port
            time.sleep(1)
    except Exception as e:
        logger.warning(f"[embed] failed to kill existing llama-server: {e}")


def _is_server_ready(endpoint: str = DEFAULT_EMBEDDING_ENDPOINT) -> bool:
    """Return True if the embedding server responds.

    The /v1/embeddings endpoint only accepts POST, so we probe /health first.
    """
    from urllib.parse import urlparse

    # Try the dedicated health endpoint (llama-server)
    try:
        parsed = urlparse(endpoint)
        health_url = f"{parsed.scheme}://{parsed.netloc}/health"
        resp = urllib.request.urlopen(health_url, timeout=2)
        if 200 <= resp.status < 300:
            return True
    except Exception:
        pass
    # Fallback: POST a dummy request to the embeddings endpoint
    try:
        req = urllib.request.Request(
            endpoint,
            data=b'{"input":["test"]}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=2)
        return resp.status == 200
    except Exception:
        return False


def _is_llama_running() -> bool:
    """Return True if llama-server.exe is still in the process list."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"],
            capture_output=True, text=True, timeout=2,
        )
        return "llama-server.exe" in result.stdout
    except Exception:
        return False


def _start_llama_server(project: str, server_log_path: str) -> subprocess.Popen | None:
    """Launch the llama-server subprocess and return the Popen handle."""
    try:
        server_log = open(server_log_path, "a", encoding="utf-8")
        bat_path = os.path.join(project, "start_embedding_server.bat")
        if os.path.exists(bat_path):
            return subprocess.Popen(
                [bat_path],
                cwd=project,
                stdout=server_log,
                stderr=subprocess.STDOUT,
            )
        # Fallback: relative paths from project directory
        return subprocess.Popen(
            [os.path.join("memory", "llama-bin", "llama-server.exe"),
             "-m", os.path.join("memory", "Qwen3.5-0.8B-Q6_K.gguf"),
             "--embeddings", "--port", "8080",
             "-ngl", "99", "--ctx-size", "2048", "--batch-size", "512",
             "--threads", "4", "--host", "127.0.0.1"],
            cwd=project,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
    except Exception:
        logger.exception("[embed] failed to launch llama-server")
        return None


def _wait_for_ready(proc: subprocess.Popen, endpoint: str,
                    server_log_path: str, log: logging.Logger) -> None:
    """Background watcher: poll the embedding server until it is ready."""
    last_logged = 0
    for i in range(MAX_WAIT_SECONDS):
        time.sleep(WAIT_POLL_INTERVAL)
        if _is_server_ready(endpoint):
            log.info(f"[embed] server ready ({i + 1}s)")
            return
        # Log progress every 10 seconds so users know it is still loading
        if (i + 1) % 10 == 0 and (i + 1) != last_logged:
            last_logged = i + 1
            log.info(f"[embed] still loading... ({i + 1}s)")
        # If the process died early, give up immediately and surface the log
        if proc.poll() is not None:
            log.warning(
                f"[embed] llama-server exited early (code {proc.returncode}), "
                f"see {server_log_path}"
            )
            return

    # Final check: server might have started right after the last poll
    if _is_server_ready(endpoint):
        log.info(f"[embed] server ready ({MAX_WAIT_SECONDS}s)")
        return

    # If process is still alive but not ready, keep it running and warn
    if _is_llama_running():
        log.warning(
            f"[embed] server still loading after {MAX_WAIT_SECONDS}s; "
            "continuing without embedding fallback"
        )
    else:
        log.warning(
            f"[embed] server did not respond within {MAX_WAIT_SECONDS}s, "
            f"falling back to keyword search (see {server_log_path})"
        )


def auto_start_embedding(logger_ref: logging.Logger | None = None,
                         endpoint: str = DEFAULT_EMBEDDING_ENDPOINT) -> None:
    """Start embedding server if not running. Non-blocking after launch."""
    log = logger_ref or logger

    if _is_server_ready(endpoint):
        log.info("[embed] server already running")
        return

    # Kill stale llama process before starting fresh
    kill_existing_llama()

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model = os.path.join(project, "memory", "Qwen3.5-0.8B-Q6_K.gguf")
    if not os.path.exists(model):
        log.info("[embed] model not found, skipping auto-start")
        return

    # Ensure logs directory exists and redirect server output for diagnostics
    log_dir = os.path.join(project, "logs")
    os.makedirs(log_dir, exist_ok=True)
    server_log_path = os.path.join(log_dir, "embedding_server.log")

    log.info("[embed] starting embedding server in background...")
    proc = _start_llama_server(project, server_log_path)
    if proc is None:
        log.warning("[embed] failed to start embedding server")
        return

    # Start watcher thread so the main application can continue booting
    watcher = threading.Thread(
        target=_wait_for_ready,
        args=(proc, endpoint, server_log_path, log),
        daemon=True,
    )
    watcher.start()
