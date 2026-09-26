from __future__ import annotations

import hmac
import os
from collections import deque
from collections.abc import AsyncIterator
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import Header, HTTPException


def public_mode() -> bool:
    return os.getenv("VERCEL") == "1" or os.getenv("VISNOTICE_PUBLIC_MODE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def require_admin(x_visnotice_admin_token: str | None = Header(default=None)) -> None:
    expected_token = os.getenv("VISNOTICE_ADMIN_TOKEN", "").strip()
    if expected_token:
        if not hmac.compare_digest(x_visnotice_admin_token or "", expected_token):
            raise HTTPException(status_code=401, detail="Admin token required.")
    elif public_mode():
        raise HTTPException(status_code=403, detail="Researcher access is disabled on this deployment.")


class PublicAnalysisLimiter:
    """Bound expensive analysis work within a single public API worker."""

    def __init__(self, max_concurrent: int = 2, max_per_minute: int = 6) -> None:
        self.max_concurrent = max_concurrent
        self.max_per_minute = max_per_minute
        self._lock = Lock()
        self._started: deque[float] = deque()
        self._active = 0

    def acquire(self) -> None:
        with self._lock:
            now = monotonic()
            while self._started and self._started[0] <= now - 60:
                self._started.popleft()
            if self._active >= self.max_concurrent:
                raise HTTPException(
                    status_code=429,
                    detail="The public analysis service is busy. Try again shortly.",
                    headers={"Retry-After": "5"},
                )
            if len(self._started) >= self.max_per_minute:
                retry_after = max(1, ceil(self._started[0] + 60 - now))
                raise HTTPException(
                    status_code=429,
                    detail="The public analysis limit was reached. Try again in a minute.",
                    headers={"Retry-After": str(retry_after)},
                )
            self._started.append(now)
            self._active += 1

    def release(self) -> None:
        with self._lock:
            self._active -= 1


analysis_limiter = PublicAnalysisLimiter()


async def limit_public_analysis() -> AsyncIterator[None]:
    if not public_mode():
        yield
        return
    analysis_limiter.acquire()
    try:
        yield
    finally:
        analysis_limiter.release()
