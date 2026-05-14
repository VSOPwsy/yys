"""TTL-bounded caches.

* `TTLCache` — primitive: count-bounded LRU + per-entry TTL.
* `CacheManager` — per-account byte-bounded cache exposed to plugins.
"""

from core.cache.lru import TTLCache
from core.cache.manager import CacheManager

__all__ = ["CacheManager", "TTLCache"]
