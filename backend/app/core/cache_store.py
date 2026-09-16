"""
Generic key-value cache with TTL support.

Backends:
  - InMemoryCache  (dev / single-instance)
  - RedisCache     (production / multi-instance)

Interface:
    get(key) -> dict | None
    set(key, value: dict, ttl_seconds) -> None
    delete(key) -> None
    exists(key) -> bool
    touch(key, ttl_seconds) -> bool
"""
from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CacheStore(ABC):
    @abstractmethod
    def get(self, key: str) -> dict | None: ...

    @abstractmethod
    def set(self, key: str, value: dict, ttl_seconds: int) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def touch(self, key: str, ttl_seconds: int) -> bool: ...


class InMemoryCache(CacheStore):
    def __init__(self) -> None:
        self._data: dict[str, tuple[dict, float]] = {}
        self._lock = threading.Lock()

    def _evict_if_expired(self, key: str) -> None:
        entry = self._data.get(key)
        if not entry:
            return
        _, expires_at = entry
        if time.time() >= expires_at:
            del self._data[key]

    def get(self, key: str) -> dict | None:
        with self._lock:
            self._evict_if_expired(key)
            entry = self._data.get(key)
            return dict(entry[0]) if entry else None

    def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = (dict(value), time.time() + ttl_seconds)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def exists(self, key: str) -> bool:
        with self._lock:
            self._evict_if_expired(key)
            return key in self._data

    def touch(self, key: str, ttl_seconds: int) -> bool:
        with self._lock:
            self._evict_if_expired(key)
            entry = self._data.get(key)
            if not entry:
                return False
            value, _ = entry
            self._data[key] = (value, time.time() + ttl_seconds)
            return True


class RedisCache(CacheStore):
    def __init__(self, redis_url: str) -> None:
        import redis
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def get(self, key: str) -> dict | None:
        raw = self._client.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        self._client.setex(key, ttl_seconds, json.dumps(value))

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._client.exists(key))

    def touch(self, key: str, ttl_seconds: int) -> bool:
        return bool(self._client.expire(key, ttl_seconds))


def build_cache(backend: str, redis_url: str | None = None) -> CacheStore:
    backend = (backend or "memory").lower()
    if backend == "redis" and redis_url:
        try:
            return RedisCache(redis_url)
        except Exception as e:
            logger.warning("Redis cache init failed (%s); falling back to memory", e)
    return InMemoryCache()