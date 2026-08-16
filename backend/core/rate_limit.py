import time
from threading import Lock

from fastapi import HTTPException, Request

from core.config import settings

_WINDOW_SECONDS = 60


class _FixedWindowLimiter:
    """In-memory per-client-IP fixed-window rate limiter.

    Single-process only, by design — matches DEPLOYMENT_PLAN.md §6's "no new
    infra" call for a solo-instance MVP. A multi-instance/multi-worker
    deployment would need a shared store (e.g. Redis) instead.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._lock = Lock()
        self._hits: dict[str, tuple[int, float]] = {}  # ip -> (count, window_start)

    def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            count, window_start = self._hits.get(ip, (0, now))
            if now - window_start >= _WINDOW_SECONDS:
                count, window_start = 0, now
            count += 1
            self._hits[ip] = (count, window_start)

        if count > self._limit:
            retry_after = int(_WINDOW_SECONDS - (now - window_start)) + 1
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )


# Two shared instances, used as FastAPI dependencies on the endpoints
# DEPLOYMENT_PLAN.md flags as unthrottled cost-abuse vectors: signup,
# profile import, and resume generation (the Gemini-call-per-request one).
default_rate_limit = _FixedWindowLimiter(settings.rate_limit_default)
generation_rate_limit = _FixedWindowLimiter(settings.rate_limit_generation)
