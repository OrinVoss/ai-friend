"""In-memory sliding-window rate limiter for the Web API."""

import logging
import threading
import time
from collections import deque
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

DEFAULT_LIMITS = {
    "/api/chat": (30, 60),          # 30 requests per 60 seconds
    "/api/status": (60, 60),        # 60 requests per 60 seconds
    "/api/chat/history": (60, 60),  # 60 requests per 60 seconds
}


class RateLimiter:
    """Simple in-memory sliding-window rate limiter keyed by client IP + path."""

    def __init__(self):
        # key -> deque of timestamps
        self._windows: dict[str, deque[float]] = {}
        # L-11: 真锁替换布尔占位 — is_allowed 的窗口读写需要原子化
        self._lock = threading.Lock()

    def _key(self, client_ip: str, path: str) -> str:
        return f"{client_ip}:{path}"

    def is_allowed(self, client_ip: str, path: str,
                   max_requests: int, window_seconds: int) -> bool:
        key = self._key(client_ip, path)
        now = time.time()
        with self._lock:
            window = self._windows.setdefault(key, deque())

            # Drop timestamps outside the window
            evicted = 0
            while window and window[0] < now - window_seconds:
                window.popleft()
                evicted += 1
            if evicted:
                logger.debug(f"[rate_limit] evicted {evicted} expired timestamps for {key}")

            if len(window) >= max_requests:
                logger.warning(f"[rate_limit] blocked {client_ip} on {path} window={len(window)}/{max_requests}")
                return False

            window.append(now)
            logger.debug(f"[rate_limit] allowed {client_ip}:{path} window={len(window)}/{max_requests}")
            return True

    def check(self, client_ip: str, path: str) -> bool:
        """Check request against configured limits. Always allowed if no limit set."""
        max_requests, window_seconds = DEFAULT_LIMITS.get(path, (0, 0))
        if max_requests <= 0:
            return True
        return self.is_allowed(client_ip, path, max_requests, window_seconds)


def get_client_ip(request: Request) -> str:
    """Extract client IP, honoring X-Forwarded-For when behind a trusted proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces per-path rate limits."""

    def __init__(self, app, limiter: RateLimiter | None = None):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        client_ip = get_client_ip(request)
        if not self.limiter.check(client_ip, path):
            logger.warning(f"[rate_limit] middleware blocked {client_ip} {request.method} {path}")
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests. Please slow down."},
            )
        logger.debug(f"[rate_limit] middleware allowed {client_ip} {request.method} {path}")
        return await call_next(request)
