from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable


class TTLCache:
    """Simple thread-safe TTL cache for API response caching."""

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl = default_ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        with self._lock:
            self._store[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired_keys = [k for k, (exp, _) in self._store.items() if now > exp]
            for k in expired_keys:
                del self._store[k]
                removed += 1
        return removed


def cached_method(cache_attr: str, key_fn: Callable[..., str], ttl_seconds: int | None = None):
    """Decorator to cache method results on self.<cache_attr> TTLCache."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            cache: TTLCache = getattr(self, cache_attr)
            key = key_fn(*args, **kwargs)
            result = cache.get(key)
            if result is not None:
                return result
            result = func(self, *args, **kwargs)
            if result is not None:
                cache.set(key, result, ttl_seconds)
            return result
        return wrapper
    return decorator
