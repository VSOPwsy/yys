"""Unit tests for `core.scheduler.throttle.Throttle`."""

from __future__ import annotations

import threading
import time

import pytest

from core.exceptions import ThrottleTimeout
from core.scheduler.throttle import Throttle


class _FakeClock:
    """Manual clock + sleep that advances `now` whenever sleep is called.

    Lets us assert exact wait amounts without flaky timing.
    """

    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


def _make(*, fc: _FakeClock, **kwargs) -> Throttle:
    return Throttle(clock=fc.time, sleep=fc.sleep, **kwargs)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_negative_min_interval_rejected():
    with pytest.raises(ValueError):
        Throttle(min_interval=-0.1)


def test_negative_max_actions_rejected():
    with pytest.raises(ValueError):
        Throttle(max_actions_per_window=-1)


def test_zero_window_with_positive_cap_rejected():
    with pytest.raises(ValueError):
        Throttle(max_actions_per_window=10, window_seconds=0)


# --------------------------------------------------------------------------- #
# Min-interval gap
# --------------------------------------------------------------------------- #
def test_first_call_does_not_block():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=0.5, max_actions_per_window=0)
    slept = t.wait()
    assert slept == 0.0
    assert fc.sleeps == []


def test_consecutive_calls_enforce_min_interval():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=0.5, max_actions_per_window=0)
    t.wait()                       # accepted at now=1000
    # No time advance between calls — second wait must sleep ~0.5s.
    slept = t.wait()
    assert slept == pytest.approx(0.5, abs=1e-6)


def test_calls_after_interval_dont_block():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=0.5, max_actions_per_window=0)
    t.wait()                       # at 1000
    fc.now = 1000.5                # full gap elapsed
    slept = t.wait()
    assert slept == 0.0


# --------------------------------------------------------------------------- #
# Window cap
# --------------------------------------------------------------------------- #
def test_window_cap_pushes_subsequent_call_to_next_slot():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=0.0, max_actions_per_window=3, window_seconds=10.0)
    # Fire 3 actions instantly.
    t.wait()
    t.wait()
    t.wait()
    # 4th must wait until the first leaves the window: 10s after 1000 = 1010.
    # No time advance happened, so we expect 10s of sleep.
    slept = t.wait()
    assert slept == pytest.approx(10.0, abs=1e-6)


def test_window_slides_with_time():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=0.0, max_actions_per_window=2, window_seconds=5.0)
    t.wait()  # at 1000
    fc.now = 1001.0
    t.wait()  # at 1001
    fc.now = 1005.5  # first call (1000) has left the window
    slept = t.wait()
    assert slept == 0.0


# --------------------------------------------------------------------------- #
# Timeout
# --------------------------------------------------------------------------- #
def test_timeout_raises_when_budget_too_tight():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=10.0, max_actions_per_window=0)
    t.wait()  # accepted immediately
    # Next call would need 10s; only allow 0.5s.
    with pytest.raises(ThrottleTimeout):
        t.wait(timeout=0.5)


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def test_total_calls_increments():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=0.0, max_actions_per_window=0)
    assert t.total_calls == 0
    for _ in range(5):
        t.wait()
    assert t.total_calls == 5


def test_reset_clears_history():
    fc = _FakeClock()
    t = _make(fc=fc, min_interval=0.0, max_actions_per_window=2, window_seconds=10.0)
    t.wait()
    t.wait()
    # Without reset, third would block.
    t.reset()
    slept = t.wait()
    assert slept == 0.0


# --------------------------------------------------------------------------- #
# Threading (real clock — small interval to keep test fast)
# --------------------------------------------------------------------------- #
def test_throttle_is_thread_safe():
    """Confirm the lock keeps history consistent under concurrent callers."""
    t = Throttle(min_interval=0.0, max_actions_per_window=0)
    barrier = threading.Barrier(8)
    def worker():
        barrier.wait()
        for _ in range(10):
            t.wait()
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert t.total_calls == 80
