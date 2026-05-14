"""TTLCache: TTL semantics, LRU eviction, thread-safe basics."""

import pytest

from core.cache.lru import TTLCache


def test_basic_set_get():
    c = TTLCache[str, int](max_size=4, default_ttl=10)
    c.set("a", 1)
    assert c.get("a") == 1
    assert c.get("missing") is None


def test_ttl_expires():
    now = [0.0]
    c = TTLCache[str, int](max_size=4, default_ttl=1.0, clock=lambda: now[0])
    c.set("a", 1)
    assert c.get("a") == 1
    now[0] = 2.0
    assert c.get("a") is None


def test_lru_evicts_oldest():
    c = TTLCache[int, int](max_size=3, default_ttl=10)
    c.set(1, 1)
    c.set(2, 2)
    c.set(3, 3)
    c.get(1)  # bump 1 to most-recently-used
    c.set(4, 4)  # should evict 2
    assert c.get(2) is None
    assert c.get(1) == 1
    assert c.get(3) == 3
    assert c.get(4) == 4


def test_invalidate_and_clear():
    c = TTLCache[str, int](max_size=4, default_ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    assert c.invalidate("a") is True
    assert c.invalidate("a") is False
    c.clear()
    assert c.get("b") is None


def test_purge_expired():
    now = [0.0]
    c = TTLCache[str, int](max_size=4, default_ttl=1.0, clock=lambda: now[0])
    c.set("a", 1)
    c.set("b", 2)
    now[0] = 2.0
    assert c.purge_expired() == 2
    assert len(c) == 0


def test_contains_respects_ttl():
    now = [0.0]
    c = TTLCache[str, int](max_size=4, default_ttl=1.0, clock=lambda: now[0])
    c.set("a", 1)
    assert "a" in c
    now[0] = 2.0
    assert "a" not in c


def test_max_size_validation():
    with pytest.raises(ValueError):
        TTLCache(max_size=0)


def test_zero_ttl_is_noop():
    c = TTLCache[str, int](max_size=4, default_ttl=10)
    c.set("a", 1, ttl=0)
    assert c.get("a") is None
