"""Per-user rate limits, so one user (or a stuck script) can't monopolise the local LLM.

A "sliding window" limiter: remember when each user's recent requests happened; if
they've made `limit` requests within the last `window` seconds, refuse the next one
with 429 Too Many Requests and a Retry-After header saying when to try again.

Counts live in this process's memory, which is fine for a single local server. With
several server processes you'd keep them in a shared store such as Redis instead.
"""

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, status

from app.auth.users import CurrentUser
from app.config import settings


class RateLimiter:
    def __init__(self, name: str, limit: int, window_seconds: float) -> None:
        self.name = name
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Record a request. Returns None if allowed, else seconds until one is allowed."""
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()  # forget requests that have left the window
        if len(hits) >= self.limit:
            return hits[0] + self.window - now
        hits.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()

    def dependency(self) -> Callable[[Any], Coroutine[Any, Any, None]]:
        """A FastAPI dependency enforcing this limit for the signed-in user.

        Being a dependency matters for streaming endpoints: it runs before the response
        starts, so a proper 429 can still be returned."""

        async def check(user: CurrentUser) -> None:
            retry_after = self.hit(str(user.id))
            if retry_after is not None:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many {self.name}. Please wait {math.ceil(retry_after)} seconds.",
                    headers={"Retry-After": str(math.ceil(retry_after))},
                )

        return check


questions = RateLimiter("questions", settings.rate_limit_questions_per_minute, 60)
uploads = RateLimiter("uploads", settings.rate_limit_uploads_per_hour, 3600)
ALL_LIMITERS = [questions, uploads]
