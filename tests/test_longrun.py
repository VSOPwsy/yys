"""Unit tests for `core.scheduler.longrun.LongRunPolicy`."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from core.scheduler.longrun import LongRunPolicy


def _make_scheduler() -> MagicMock:
    """A scheduler mock that runs `submit`-ed callables synchronously."""
    sched = MagicMock()
    sched.submit.side_effect = lambda fn: fn()
    return sched


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_invalid_durations_rejected():
    s = _make_scheduler()
    with pytest.raises(ValueError):
        LongRunPolicy(s, daily_max_runtime=0, rest_every=0, rest_duration=0)
    with pytest.raises(ValueError):
        LongRunPolicy(s, daily_max_runtime=100, rest_every=-1, rest_duration=10)
    with pytest.raises(ValueError):
        LongRunPolicy(s, daily_max_runtime=100, rest_every=10, rest_duration=0)


# --------------------------------------------------------------------------- #
# Daily cap
# --------------------------------------------------------------------------- #
def test_daily_cap_stops_all_and_fires_callback():
    """When elapsed >= daily_max, the watchdog stops everything and fires the cb."""
    s = _make_scheduler()
    cb_event = threading.Event()
    policy = LongRunPolicy(
        s,
        daily_max_runtime=0.05,
        rest_every=0,                  # disable rest cycles
        rest_duration=0,
        tick_interval=0.01,
        on_daily_cap_reached=cb_event.set,
    )
    policy.start()
    assert cb_event.wait(timeout=2.0)
    # Submitted stop_all; mock dispatched synchronously.
    s.stop_all.assert_called()
    assert policy.daily_cap_triggered is True
    policy.stop()


# --------------------------------------------------------------------------- #
# Rest cycle
# --------------------------------------------------------------------------- #
def test_rest_cycle_pauses_then_resumes():
    """Within one rest interval the watchdog calls pause_all then resume_all."""
    s = _make_scheduler()
    policy = LongRunPolicy(
        s,
        daily_max_runtime=10.0,       # large so daily cap doesn't fire first
        rest_every=0.05,
        rest_duration=0.05,
        tick_interval=0.01,
    )
    policy.start()
    # Wait long enough for one full rest cycle.
    time.sleep(0.3)
    policy.stop()
    # Both pause_all and resume_all should have been called at least once.
    assert s.pause_all.called
    assert s.resume_all.called


def test_rest_disabled_when_rest_every_zero():
    """rest_every=0 means no rest cycles ever fire."""
    s = _make_scheduler()
    policy = LongRunPolicy(
        s,
        daily_max_runtime=10.0,
        rest_every=0,
        rest_duration=0,
        tick_interval=0.01,
    )
    policy.start()
    time.sleep(0.1)
    policy.stop()
    assert not s.pause_all.called


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def test_start_is_idempotent():
    s = _make_scheduler()
    policy = LongRunPolicy(
        s, daily_max_runtime=10, rest_every=0, rest_duration=0,
        tick_interval=0.05,
    )
    policy.start()
    t1 = policy._thread
    policy.start()
    t2 = policy._thread
    assert t1 is t2
    policy.stop()


def test_stop_joins_thread():
    s = _make_scheduler()
    policy = LongRunPolicy(
        s, daily_max_runtime=10, rest_every=0, rest_duration=0,
        tick_interval=0.05,
    )
    policy.start()
    policy.stop()
    assert policy._thread is None
