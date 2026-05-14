"""
Thread-safe LRU with per-entry TTL.

Designed for template-image and screenshot caching: small N, hot access,
expiry measured in seconds. Built on `collections.OrderedDict` so we get
O(1) move-to-end on access without pulling in a heavy dependency.

Single-account scope: instantiate one per consumer (per backend / per
account_id). Sharing one cache across accounts is fine for *immutable*
content like template PNGs (see `TemplateRepository`), but never for
screenshots.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable, Generic, Hashable, Iterator, Optional, Tuple, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

_MISSING = object()


class TTLCache(Generic[K, V]):
    """LRU cache where each entry also has an absolute expiry timestamp.

    On `get`, an entry past its TTL is evicted and treated as a miss.
    On insert, if size would exceed `max_size`, the least-recently-used
    entry is dropped.
    """

    def __init__(
        self,
        max_size: int = 128,
        default_ttl: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Construct an empty cache.

        Args:
            max_size: Hard upper bound on number of live entries. Must be > 0.
            default_ttl: TTL (seconds) applied when `set` is called without an
                explicit `ttl`. Use ``float('inf')`` to keep entries until
                evicted by LRU pressure.
            clock: Time source. Override in tests; defaults to monotonic so
                results are immune to wall-clock jumps.

        Raises:
            ValueError: If `max_size <= 0` or `default_ttl < 0`.
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be > 0, got {max_size}")
        if default_ttl < 0:
            raise ValueError(f"default_ttl must be >= 0, got {default_ttl}")
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._clock = clock
        self._lock = threading.RLock()
        self._data: "OrderedDict[K, Tuple[V, float]]" = OrderedDict()

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Return the live value for `key`, or `default` if missing/expired.

        On hit, the entry is bumped to most-recently-used.
        On expiry, the entry is silently evicted.
        """
        with self._lock:
            entry = self._data.get(key, _MISSING)
            if entry is _MISSING:
                return default
            value, expires_at = entry  # type: ignore[misc]
            if self._clock() >= expires_at:
                del self._data[key]
                return default
            self._data.move_to_end(key)
            return value

    def set(self, key: K, value: V, ttl: Optional[float] = None) -> None:
        """Insert / overwrite an entry.

        Args:
            key: Hashable key.
            value: Stored as-is (no defensive copy; immutable values
                preferred).
            ttl: Seconds until expiry. ``None`` uses `default_ttl`. ``0`` is
                a no-op (immediately-expired entries are not inserted).

        Side effects:
            Evicts the LRU entry if `max_size` would be exceeded.
        """
        effective = self._default_ttl if ttl is None else ttl
        if effective <= 0:
            # Keep semantics simple: TTL=0 = "don't cache".
            self.invalidate(key)
            return
        expires_at = self._clock() + effective
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, expires_at)
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def invalidate(self, key: K) -> bool:
        """Drop a single entry. Returns True if it was present, else False."""
        with self._lock:
            return self._data.pop(key, _MISSING) is not _MISSING

    def clear(self) -> None:
        """Drop every entry."""
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        """Number of entries, including any that are already past TTL.

        Callers who want a strict live count should call `purge_expired` first.
        """
        with self._lock:
            return len(self._data)

    def __contains__(self, key: object) -> bool:
        """True iff `key` has a live (unexpired) entry."""
        with self._lock:
            entry = self._data.get(key, _MISSING)  # type: ignore[arg-type]
            if entry is _MISSING:
                return False
            _, expires_at = entry  # type: ignore[misc]
            if self._clock() >= expires_at:
                del self._data[key]  # type: ignore[arg-type]
                return False
            return True

    def purge_expired(self) -> int:
        """Evict every entry past its TTL. Returns count evicted."""
        now = self._clock()
        with self._lock:
            stale = [k for k, (_, exp) in self._data.items() if exp <= now]
            for k in stale:
                del self._data[k]
            return len(stale)

    def keys(self) -> Iterator[K]:
        """Snapshot iterator over keys (includes possibly-expired entries).

        Intentionally returns a snapshot list iterator so callers can mutate
        the cache during iteration.
        """
        with self._lock:
            return iter(list(self._data.keys()))
