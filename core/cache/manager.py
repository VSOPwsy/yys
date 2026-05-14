"""
`CacheManager` — per-account, byte-budgeted, TTL-aware cache.

Two layers of cache live in the project:

* `core.cache.lru.TTLCache` is the low-level primitive: O(1) LRU with a
  per-entry TTL, sized by *count*. Used internally by `TemplateRepository`
  (shared across accounts, immutable PNGs).

* `CacheManager` is the higher-level cache exposed to plugins via
  `PluginContext`. It is sized by **approximate bytes** because the things
  plugins typically cache are screenshots (numpy arrays, MB-sized), not
  scalar values. Each instance is bound to one `account_id` so the live
  set never bleeds between accounts (CLAUDE.md S5).

Eviction policy: when total bytes would exceed `max_bytes`, drop the LRU
entry until we fit. Expired entries are dropped on access (lazy) and via
`purge_expired()` (proactive).

We deliberately do *not* try to be clever about copies. The contract is
"caller owns the value, mutating it after `set` is undefined behavior".
That matches `TTLCache` and lets us pass huge ndarrays around without
doubling memory.
"""

from __future__ import annotations

import sys
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional, Tuple

import numpy as np

from core.logging_config import get_logger

log = get_logger(__name__)

# Default 100 MB budget — large enough to keep a recent screenshot history
# without ballooning memory on multi-account runs. Tunable per instance.
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
# Default TTL applied when neither `set()` nor `ttl=` is given.
DEFAULT_TTL = 300.0
# Screenshots churn fast; keep them short by default.
DEFAULT_SCREENSHOT_TTL = 60.0


def _estimate_bytes(value: Any) -> int:
    """Best-effort byte size of `value` for the budget accounting.

    Optimized for numpy arrays (the dominant cache value); falls back to
    `sys.getsizeof` for everything else. Underestimates compound objects
    (lists of arrays, dicts) but that's fine — accounting is a heuristic,
    not a guarantee.
    """
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(value)
    if isinstance(value, str):
        # 2 bytes/char is a rough mid-estimate (Py 3 strings are PEP 393).
        return len(value) * 2
    try:
        return int(sys.getsizeof(value))
    except (TypeError, AttributeError):
        return 1024  # arbitrary safe non-zero default


class CacheManager:
    """Per-account, byte-bounded LRU + per-entry TTL.

    Public API is a stable subset of "dict that forgets". The class is
    thread-safe (RLock) because plugins and their worker thread share it.
    """

    def __init__(
        self,
        account_id: str,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        default_ttl: float = DEFAULT_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Construct an empty cache bound to `account_id`.

        Args:
            account_id: Owning account. Stored for logs and to satisfy the
                "no shared state across accounts" rule.
            max_bytes: Soft upper bound on total stored value bytes. Setting
                a single entry larger than this is allowed (it will be the
                only thing in the cache); setting many smaller entries
                triggers LRU eviction.
            default_ttl: Seconds-until-expiry used when `set()` is called
                without `ttl=`. `inf` = "never expire, LRU only".
            clock: Time source override (tests).

        Raises:
            ValueError: empty `account_id`, non-positive `max_bytes`, or
                negative `default_ttl`.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be > 0, got {max_bytes}")
        if default_ttl < 0:
            raise ValueError(f"default_ttl must be >= 0, got {default_ttl}")

        self._account_id = account_id
        self._max_bytes = int(max_bytes)
        self._default_ttl = float(default_ttl)
        self._clock = clock
        self._lock = threading.RLock()
        # value tuple: (value, expires_at, size_bytes)
        self._data: "OrderedDict[Hashable, Tuple[Any, float, int]]" = OrderedDict()
        self._total_bytes = 0

    # ------------------------------------------------------------------ #
    # Identity / introspection
    # ------------------------------------------------------------------ #
    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def total_bytes(self) -> int:
        """Sum of estimated sizes of currently-stored entries."""
        with self._lock:
            return self._total_bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            entry = self._data.get(key)  # type: ignore[arg-type]
            if entry is None:
                return False
            _, expires_at, _ = entry
            if self._clock() >= expires_at:
                self._drop(key)  # type: ignore[arg-type]
                return False
            return True

    # ------------------------------------------------------------------ #
    # Core operations
    # ------------------------------------------------------------------ #
    def get(
        self,
        key: Hashable,
        loader: Optional[Callable[[], Any]] = None,
        *,
        ttl: Optional[float] = None,
    ) -> Optional[Any]:
        """Return live value for `key`, falling back to `loader()` on miss.

        Args:
            key: Hashable.
            loader: Zero-arg callable. If provided and we have a miss, it is
                called *outside* the lock, and its result is stored under
                `key` (with `ttl` or `default_ttl`) before being returned.
                A loader that raises propagates unchanged — nothing is
                stored.
            ttl: Override TTL when storing the loader result.

        Returns:
            The stored value, the freshly-loaded value, or `None` if there
            was a miss and no loader.
        """
        with self._lock:
            entry = self._data.get(key)
            if entry is not None:
                value, expires_at, _ = entry
                if self._clock() < expires_at:
                    self._data.move_to_end(key)
                    return value
                self._drop(key)
        if loader is None:
            return None
        value = loader()
        self.set(key, value, ttl=ttl)
        return value

    def set(
        self,
        key: Hashable,
        value: Any,
        *,
        ttl: Optional[float] = None,
    ) -> None:
        """Insert or replace an entry.

        Args:
            key: Hashable.
            value: Stored as-is, no defensive copy.
            ttl: Seconds-until-expiry. `None` -> `default_ttl`. `0` is a
                no-op equivalent to invalidate (matches `TTLCache`).
        """
        effective = self._default_ttl if ttl is None else float(ttl)
        if effective <= 0:
            self.invalidate(key)
            return
        size = _estimate_bytes(value)
        expires_at = self._clock() + effective
        with self._lock:
            old = self._data.pop(key, None)
            if old is not None:
                self._total_bytes -= old[2]
            self._data[key] = (value, expires_at, size)
            self._total_bytes += size
            self._evict_if_needed()

    def set_screenshot(
        self,
        key: Hashable,
        image: np.ndarray,
        *,
        ttl: float = DEFAULT_SCREENSHOT_TTL,
    ) -> None:
        """Cache a screenshot with a short TTL by default.

        Sugar over `set()` that makes the intent obvious and centralizes
        the default freshness window. Raises ValueError if `image` is not
        an ndarray (a screenshot cache that accepts strings is almost
        always a bug).
        """
        if not isinstance(image, np.ndarray):
            raise ValueError(
                f"set_screenshot expects np.ndarray, got {type(image).__name__}"
            )
        self.set(key, image, ttl=ttl)

    def invalidate(self, key: Hashable) -> bool:
        """Drop a single entry. Returns True iff it was present."""
        with self._lock:
            return self._drop(key)

    def clear(self) -> None:
        """Drop every entry."""
        with self._lock:
            self._data.clear()
            self._total_bytes = 0

    def purge_expired(self) -> int:
        """Drop every entry past TTL. Returns count evicted."""
        now = self._clock()
        with self._lock:
            stale = [k for k, (_, exp, _) in self._data.items() if exp <= now]
            for k in stale:
                self._drop(k)
            return len(stale)

    # ------------------------------------------------------------------ #
    # Internal helpers (must be called under the lock)
    # ------------------------------------------------------------------ #
    def _drop(self, key: Hashable) -> bool:
        entry = self._data.pop(key, None)
        if entry is None:
            return False
        self._total_bytes -= entry[2]
        return True

    def _evict_if_needed(self) -> None:
        while self._total_bytes > self._max_bytes and self._data:
            evicted_key, (_, _, size) = self._data.popitem(last=False)
            self._total_bytes -= size
            log.debug(
                "[%s] cache eviction: dropped %r (%d bytes), total=%d/%d",
                self._account_id, evicted_key, size,
                self._total_bytes, self._max_bytes,
            )

    def __repr__(self) -> str:
        return (
            f"<CacheManager account={self._account_id!r} "
            f"entries={len(self._data)} "
            f"bytes={self._total_bytes}/{self._max_bytes}>"
        )
