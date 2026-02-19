"""
TTL caching layer for Agent 04 tools.

Why cache here
--------------
All three tools (data fetcher, Chronos, GARCH/MC) are deterministic given
the same inputs within a short window:
  - yfinance prices don't change meaningfully within 1 hour
  - Model outputs (Chronos paths, GARCH params, MC scenarios) are fully
    determined by the input price series, which itself comes from the cache

A single pipeline run for one ticker costs ~10–15s without cache.
A repeated run for the same ticker (e.g. re-analysis, retry after critic
failure, or a second user querying the same asset) costs ~0s with cache.

Cache design
------------
Two separate caches with different TTLs:
  DATA_CACHE   — yfinance OHLCV results          — 60 min TTL
  MODEL_CACHE  — Chronos / GARCH / MC results    — 30 min TTL

Both caches are bounded (maxsize=128) so they don't grow unboundedly
in a long-running Celery worker process.

Thread safety
-------------
cachetools is not thread-safe by default. We wrap each cache with a
threading.Lock so concurrent Celery tasks don't corrupt cache state.

Usage
-----
    from .cache import get_cached, set_cached, CacheNamespace

    result = get_cached(CacheNamespace.DATA, key)
    if result is None:
        result = expensive_call()
        set_cached(CacheNamespace.DATA, key, result)
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Optional

from cachetools import TTLCache


# ---------------------------------------------------------------------------
# Cache instances
# ---------------------------------------------------------------------------

_DATA_CACHE: TTLCache  = TTLCache(maxsize=128, ttl=60 * 60)       # 60 min
_MODEL_CACHE: TTLCache = TTLCache(maxsize=128, ttl=30 * 60)        # 30 min

_DATA_LOCK  = threading.Lock()
_MODEL_LOCK = threading.Lock()


class CacheNamespace(str, Enum):
    DATA  = "data"   # yfinance OHLCV results
    MODEL = "model"  # Chronos / GARCH / Monte Carlo results


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def make_key(*parts: Any) -> str:
    """
    Build a deterministic string cache key from arbitrary parts.

    Example:
        make_key("GC=F", 90)          → "GC=F::90"
        make_key("GC=F", 90, 30)      → "GC=F::90::30"
        make_key("chronos", "GC=F", 90, 30) → "chronos::GC=F::90::30"
    """
    return "::".join(str(p) for p in parts)


def get_cached(namespace: CacheNamespace, key: str) -> Optional[Any]:
    """Return the cached value for *key*, or None if missing / expired."""
    cache, lock = _resolve(namespace)
    with lock:
        return cache.get(key)


def set_cached(namespace: CacheNamespace, key: str, value: Any) -> None:
    """Store *value* under *key* in the appropriate cache."""
    cache, lock = _resolve(namespace)
    with lock:
        cache[key] = value


def invalidate(namespace: CacheNamespace, key: str) -> None:
    """Explicitly evict a single entry (useful in tests)."""
    cache, lock = _resolve(namespace)
    with lock:
        cache.pop(key, None)


def clear_all() -> None:
    """Flush both caches — intended for tests only."""
    with _DATA_LOCK:
        _DATA_CACHE.clear()
    with _MODEL_LOCK:
        _MODEL_CACHE.clear()


def cache_stats() -> dict[str, Any]:
    """Return current size and max-size for both caches — for observability."""
    with _DATA_LOCK:
        data_size = len(_DATA_CACHE)
    with _MODEL_LOCK:
        model_size = len(_MODEL_CACHE)
    return {
        "data_cache":  {"size": data_size,  "maxsize": _DATA_CACHE.maxsize,  "ttl_seconds": _DATA_CACHE.ttl},
        "model_cache": {"size": model_size, "maxsize": _MODEL_CACHE.maxsize, "ttl_seconds": _MODEL_CACHE.ttl},
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _resolve(namespace: CacheNamespace) -> tuple[TTLCache, threading.Lock]:
    if namespace == CacheNamespace.DATA:
        return _DATA_CACHE, _DATA_LOCK
    return _MODEL_CACHE, _MODEL_LOCK
