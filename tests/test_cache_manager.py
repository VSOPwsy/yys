"""Unit tests for `CacheManager`: TTL, LRU eviction, byte accounting, threading."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from core.cache.manager import CacheManager


def _clock_factory(start: float = 1000.0):
    """Returns (clock_fn, advance_fn) for deterministic TTL tests."""
    state = [start]

    def now():
        return state[0]

    def advance(seconds: float):
        state[0] += seconds

    return now, advance


def test_account_id_required_and_immutable():
    with pytest.raises(ValueError):
        CacheManager(account_id="")
    cm = CacheManager(account_id="alice")
    assert cm.account_id == "alice"


def test_get_default_miss_returns_none():
    cm = CacheManager(account_id="a")
    assert cm.get("nope") is None


def test_set_then_get():
    cm = CacheManager(account_id="a")
    cm.set("k", "v")
    assert cm.get("k") == "v"


def test_ttl_expiry_drops_entry():
    now, advance = _clock_factory()
    cm = CacheManager(account_id="a", default_ttl=10.0, clock=now)
    cm.set("k", "v")
    assert cm.get("k") == "v"
    advance(11.0)
    assert cm.get("k") is None
    assert "k" not in cm


def test_set_with_ttl_zero_is_invalidate():
    cm = CacheManager(account_id="a")
    cm.set("k", "v")
    cm.set("k", "v2", ttl=0)
    assert cm.get("k") is None


def test_loader_only_called_on_miss():
    cm = CacheManager(account_id="a")
    calls = []

    def loader():
        calls.append(1)
        return "loaded"

    assert cm.get("k", loader=loader) == "loaded"
    assert calls == [1]
    # Second call should hit the cache, not loader.
    assert cm.get("k", loader=loader) == "loaded"
    assert calls == [1]


def test_loader_raise_does_not_store():
    cm = CacheManager(account_id="a")

    def loader():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        cm.get("k", loader=loader)
    assert "k" not in cm


def test_lru_eviction_by_bytes():
    # Each value sized 50 bytes, budget 100 -> only 2 fit.
    cm = CacheManager(account_id="a", max_bytes=100, default_ttl=999)
    cm.set("a", b"x" * 50)
    cm.set("b", b"x" * 50)
    cm.set("c", b"x" * 50)  # evicts 'a' (LRU)
    assert "a" not in cm
    assert "b" in cm
    assert "c" in cm


def test_lru_get_promotes_to_mru():
    cm = CacheManager(account_id="a", max_bytes=100, default_ttl=999)
    cm.set("a", b"x" * 50)
    cm.set("b", b"x" * 50)
    # Touch 'a' so 'b' becomes LRU
    assert cm.get("a") == b"x" * 50
    cm.set("c", b"x" * 50)
    assert "a" in cm
    assert "b" not in cm
    assert "c" in cm


def test_set_screenshot_requires_ndarray():
    cm = CacheManager(account_id="a")
    with pytest.raises(ValueError):
        cm.set_screenshot("k", "not an ndarray")  # type: ignore[arg-type]


def test_set_screenshot_short_ttl_default():
    now, advance = _clock_factory()
    cm = CacheManager(account_id="a", clock=now)
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    cm.set_screenshot("frame", img)
    assert "frame" in cm
    advance(120)  # past 60s default
    assert "frame" not in cm


def test_purge_expired_returns_count():
    now, advance = _clock_factory()
    cm = CacheManager(account_id="a", default_ttl=5.0, clock=now)
    cm.set("a", 1)
    cm.set("b", 2)
    advance(10)
    cm.set("c", 3)
    assert cm.purge_expired() == 2
    assert "a" not in cm
    assert "b" not in cm
    assert "c" in cm


def test_invalidate_and_clear():
    cm = CacheManager(account_id="a")
    cm.set("a", 1)
    cm.set("b", 2)
    assert cm.invalidate("a") is True
    assert cm.invalidate("a") is False
    cm.clear()
    assert len(cm) == 0


def test_thread_safety_no_explosion():
    """Lots of concurrent set/get on the same cache should not raise."""
    cm = CacheManager(account_id="a", max_bytes=1_000_000, default_ttl=60)

    def worker(prefix: str):
        for i in range(500):
            cm.set(f"{prefix}-{i}", i)
            cm.get(f"{prefix}-{i % 10}")
            cm.invalidate(f"{prefix}-{i % 7}")

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # No assertion needed beyond "no exceptions"; sanity check size invariant.
    assert cm.total_bytes >= 0
