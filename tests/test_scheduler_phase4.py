"""
Phase 4-specific scheduler tests: inter-plugin gap + AccountBusy + start_all
with concurrent_plugins=False.
"""

from __future__ import annotations

import threading
import time

import pytest

from core.exceptions import AccountBusy
from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin
from core.scheduler.registry import PluginRegistry
from core.scheduler.scheduler import AccountRuntime, Scheduler
from core.scheduler.worker import WorkerStatus


class _LongLoop(GameplayPlugin):
    name = "looper_a"

    @classmethod
    def build_subgraph(cls):
        return GameGraph()

    def __init__(self):
        super().__init__()
        self.run_started = threading.Event()
        self.iterations = 0

    def setup(self, ctx): pass

    def run(self, ctx):
        self.run_started.set()
        while not ctx.should_stop():
            self.iterations += 1
            if ctx.sleep(0.01):
                return

    def teardown(self, ctx): pass


class _LongLoopB(_LongLoop):
    name = "looper_b"


def _runtime(account_id="alice"):
    return AccountRuntime(
        account_id=account_id,
        backend=None,  # type: ignore[arg-type]
        graph=GameGraph(),
        navigator=None,  # type: ignore[arg-type]
        matcher=None,  # type: ignore[arg-type]
        cache=None,  # type: ignore[arg-type]
        ocr=None,
    )


def _registry(*classes) -> PluginRegistry:
    r = PluginRegistry()
    for c in classes:
        r.register(c)
    return r


# --------------------------------------------------------------------------- #
# concurrent_plugins=False (default)
# --------------------------------------------------------------------------- #
def test_account_busy_raised_when_second_plugin_starts():
    sched = Scheduler(_registry(_LongLoop, _LongLoopB))
    sched.register_account(_runtime())
    w1 = sched.start_plugin("looper_a", "alice")
    try:
        w1.plugin.run_started.wait(timeout=1.0)
        with pytest.raises(AccountBusy):
            sched.start_plugin("looper_b", "alice")
    finally:
        sched.stop_all(timeout=2.0)


def test_second_plugin_ok_after_first_stopped():
    """After plugin A stops, plugin B can start (no busy state)."""
    sched = Scheduler(_registry(_LongLoop, _LongLoopB))
    sched.register_account(_runtime())
    sched.start_plugin("looper_a", "alice")
    sched.stop_plugin("looper_a", "alice", timeout=2.0)
    # Second plugin can now start.
    w2 = sched.start_plugin("looper_b", "alice")
    try:
        w2.plugin.run_started.wait(timeout=1.0)
    finally:
        sched.stop_all(timeout=2.0)


def test_account_busy_does_not_apply_across_accounts():
    sched = Scheduler(_registry(_LongLoop, _LongLoopB))
    sched.register_account(_runtime("alice"))
    sched.register_account(_runtime("bob"))
    sched.start_plugin("looper_a", "alice")
    # Different account — should be allowed even with concurrent_plugins=False.
    sched.start_plugin("looper_a", "bob")
    sched.stop_all(timeout=2.0)


# --------------------------------------------------------------------------- #
# inter_plugin_gap
# --------------------------------------------------------------------------- #
def test_inter_plugin_gap_delays_start(monkeypatch):
    sched = Scheduler(
        _registry(_LongLoop, _LongLoopB),
        inter_plugin_gap=0.3,
    )
    sched.register_account(_runtime())
    sched.start_plugin("looper_a", "alice")
    sched.stop_plugin("looper_a", "alice", timeout=2.0)

    # Now the gap should kick in for the next start_plugin call.
    sleep_calls = []
    real_sleep = time.sleep

    def spy_sleep(s):
        sleep_calls.append(s)
        real_sleep(min(s, 0.01))  # short-circuit but record
    monkeypatch.setattr("core.scheduler.scheduler.time.sleep", spy_sleep)

    sched.start_plugin("looper_b", "alice")
    sched.stop_all(timeout=2.0)
    # We should have slept at least once for the gap.
    assert any(s > 0 for s in sleep_calls)


def test_inter_plugin_gap_zero_skips_sleep(monkeypatch):
    sched = Scheduler(_registry(_LongLoop, _LongLoopB))  # default gap=0
    sched.register_account(_runtime())
    sched.start_plugin("looper_a", "alice")
    sched.stop_plugin("looper_a", "alice", timeout=2.0)

    sleeps = []
    monkeypatch.setattr(
        "core.scheduler.scheduler.time.sleep", lambda s: sleeps.append(s)
    )
    sched.start_plugin("looper_b", "alice")
    sched.stop_all(timeout=2.0)
    # No gap configured — scheduler should not have called sleep for gap.
    assert sleeps == []
