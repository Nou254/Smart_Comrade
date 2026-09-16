"""
Rate limit storage backends.

Two implementations:
  - InMemoryStore    (dev / single-instance)
  - RedisStore       (production / multi-instance)

Both share the same interface:

    hit(key, window_seconds) -> current_count
    reset(key)
    ttl(key) -> seconds_remaining
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict

logger = logging.getLogger(__name__)


class RateLimitStore(ABC):
    @abstractmethod
    def hit(self, key: str, window_seconds: int) -> int:
        """Increment counter for key; return current count in the window."""

    @abstractmethod
    def peek(self, key: str) -> int:
        """Return current count without incrementing."""

    @abstractmethod
    def reset(self, key: str) -> None:
        """Clear the counter for key."""

    @abstractmethod
    def ttl(self, key: str) -> int:
        """Seconds until the current window expires (0 if none)."""


# ── In-memory ──────────────────────────────────────────────────

class InMemoryStore(RateLimitStore):
    """
    Fixed-window counter with TTL eviction.

    Stores per-key: (count, window_start_ts, window_seconds)
    Thread-safe via a lock.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[int, float, int]] = {}
        self._lock = threading.Lock()

    def _evict_if_expired(self, key: str) -> None:
        entry = self._data.get(key)
        if not entry:
            return
        _, started, window = entry
        if time.time() - started >= window:
            del self._data[key]

    def hit(self, key: str, window_seconds: int) -> int:
        with self._lock:
            self._evict_if_expired(key)
            entry = self._data.get(key)
            now = time.time()
            if not entry:
                self._data[key] = (1, now, window_seconds)
                return 1
            count, started, window = entry
            count += 1
            self._data[key] = (count, started, window)
            return count

    def peek(self, key: str) -> int:
        with self._lock:
            self._evict_if_expired(key)
            entry = self._data.get(key)
            return entry[0] if entry else 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def ttl(self, key: str) -> int:
        with self._lock:
            self._evict_if_expired(key)
            entry = self._data.get(key)
            if not entry:
                return 0
            _, started, window = entry
            remaining = int(window - (time.time() - started))
            return max(remaining, 0)


# ── Redis ──────────────────────────────────────────────────────

class RedisStore(RateLimitStore):
    """
    Uses INCR + EXPIRE for fixed-window counting.
    """

    def __init__(self, redis_url: str) -> None:
        try:
            import redis  # noqa: F401
        except ImportError as e:
            raise RuntimeError("redis package is not installed") from e

        import redis

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def hit(self, key: str, window_seconds: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key, 1)
        pipe.ttl(key)
        count, ttl = pipe.execute()

        # If this is the first hit, set TTL
        if ttl == -1:
            self._client.expire(key, window_seconds)
            ttl = window_seconds

        return int(count)

    def peek(self, key: str) -> int:
        value = self._client.get(key)
        return int(value) if value else 0

    def reset(self, key: str) -> None:
        self._client.delete(key)

    def ttl(self, key: str) -> int:
        t = self._client.ttl(key)
        return max(int(t), 0)


# ── Factory ────────────────────────────────────────────────────

def build_store(backend: str, redis_url: str | None = None) -> RateLimitStore:
    backend = (backend or "memory").lower()
    if backend == "redis" and redis_url:
        try:
            return RedisStore(redis_url)
        except Exception as e:
            logger.warning("Redis rate-limit store init failed (%s); falling back", e)
    return InMemoryStore()