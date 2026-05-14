"""Integration-ish tests for `Scheduler`: start/stop, command queue, multi-plugin."""

from __future__ import annotations

import logging
import threading
import time

import pytest

from core.exceptions import (
    AccountBusy,
    AccountNotRegistered,
    PluginNotRegistered,
    PluginRequirementUnmet,
    WorkerAlreadyRunning,
)
from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin
from core.scheduler.registry import PluginRegistry
from core.scheduler.scheduler import AccountRuntime, Scheduler
from core.scheduler.worker import WorkerStatus


class _LongLoopPlugin(GameplayPlugin):
    """Stays in run() until stop is signalled. Iteration count exposed."""

    name = "looper"
    requires_vertices = []

    @classmethod
    def build_subgraph(cls):  # pragma: no cover
        return GameGraph()

    def __init__(self):
        super().__init__()
        self.iterations = 0
        self.run_started = threading.Event()

    def setup(self, ctx):
        pass

    def run(self, ctx):
        self.run_started.set()
        while not ctx.should_stop():
            self.iterations += 1
            if ctx.sleep(0.01):
                return

    def teardown(self, ctx):
        pass


class _OnceLooper(_LongLoopPlugin):
    name = "looper_b"


class _NeedsVertex(GameplayPlugin):
    name = "picky"
    requires_vertices = ["nonexistent.vertex"]

    @classmethod
    def build_subgraph(cls):  # pragma: no cover
        return GameGraph()

    def setup(self, ctx):
        pass

    def run(self, ctx):  # pragma: no cover
        pass

    def teardown(self, ctx):
        pass


def _make_runtime(account_id: str, graph: GameGraph | None = None) -> AccountRuntime:
    """Build an AccountRuntime with all non-essential fields mocked.

    Worker construction only needs the graph + navigator references to
    exist; the test plugins don't call into them.
    """
    g = graph or GameGraph()
    return AccountRuntime(
        account_id=account_id,
        backend=None,  # type: ignore[arg-type]
        graph=g,
        navigator=None,  # type: ignore[arg-type]
        matcher=None,  # type: ignore[arg-type]
        cache=None,  # type: ignore[arg-type]
        ocr=None,
    )


def _make_registry(*plugin_classes) -> PluginRegistry:
    reg = PluginRegistry()
    for cls in plugin_classes:
        reg.register(cls)
    return reg


def test_start_plugin_requires_account():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    with pytest.raises(AccountNotRegistered):
        sched.start_plugin("looper", "missing")


def test_start_plugin_requires_known_plugin():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice"))
    with pytest.raises(PluginNotRegistered):
        sched.start_plugin("unknown", "alice")


def test_start_plugin_runs_and_stop_works():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice"))
    worker = sched.start_plugin("looper", "alice")
    try:
        assert worker.plugin.run_started.wait(timeout=1.0)
        assert worker.status == WorkerStatus.RUNNING
        statuses = sched.list_status()
        assert statuses == {"alice": {"looper": WorkerStatus.RUNNING}}
    finally:
        assert sched.stop_plugin("looper", "alice", timeout=2.0)
    assert worker.status == WorkerStatus.STOPPED
    assert worker.plugin.iterations > 0


def test_double_start_raises_already_running():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice"))
    sched.start_plugin("looper", "alice")
    try:
        with pytest.raises(WorkerAlreadyRunning):
            sched.start_plugin("looper", "alice")
    finally:
        sched.stop_all(timeout=2.0)


def test_requires_vertices_enforced():
    reg = _make_registry(_NeedsVertex)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice"))  # empty graph
    with pytest.raises(PluginRequirementUnmet):
        sched.start_plugin("picky", "alice")


def test_multi_plugin_per_account_blocked_by_default():
    """Phase 4 default: second plugin on the same account raises AccountBusy."""
    reg = _make_registry(_LongLoopPlugin, _OnceLooper)
    sched = Scheduler(reg)  # concurrent_plugins=False is the default
    sched.register_account(_make_runtime("alice"))
    w1 = sched.start_plugin("looper", "alice")
    try:
        w1.plugin.run_started.wait(timeout=1.0)
        with pytest.raises(AccountBusy):
            sched.start_plugin("looper_b", "alice")
    finally:
        sched.stop_all(timeout=2.0)


def test_multi_plugin_per_account_opt_in():
    """Concurrent plugins are still possible when explicitly opted in."""
    reg = _make_registry(_LongLoopPlugin, _OnceLooper)
    sched = Scheduler(reg, concurrent_plugins=True)
    sched.register_account(_make_runtime("alice"))
    sched.start_plugin("looper", "alice")
    sched.start_plugin("looper_b", "alice")
    try:
        statuses = sched.list_status()["alice"]
        assert set(statuses.keys()) == {"looper", "looper_b"}
        assert all(s == WorkerStatus.RUNNING for s in statuses.values())
    finally:
        sched.stop_all(timeout=2.0)
    for s in sched.list_status()["alice"].values():
        assert s == WorkerStatus.STOPPED


def test_command_queue_dispatches_callable():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice"))
    sched.start()
    sched.start_plugin("looper", "alice")
    try:
        # Hand the scheduler a command to stop its own worker.
        flag = threading.Event()

        def cmd():
            sched.stop_plugin("looper", "alice", timeout=2.0)
            flag.set()

        sched.submit(cmd)
        assert flag.wait(timeout=3.0)
        assert sched.list_status()["alice"]["looper"] == WorkerStatus.STOPPED
    finally:
        sched.shutdown()


def test_pause_resume_round_trip():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice"))
    worker = sched.start_plugin("looper", "alice")
    try:
        worker.plugin.run_started.wait(timeout=1.0)
        sched.pause_plugin("looper", "alice")
        assert worker.status == WorkerStatus.PAUSED
        sched.resume_plugin("looper", "alice")
        time.sleep(0.05)
        assert worker.status == WorkerStatus.RUNNING
    finally:
        sched.stop_all(timeout=2.0)


def test_pause_all_then_toggle():
    reg = _make_registry(_LongLoopPlugin, _OnceLooper)
    # Opt in to concurrent plugins so we can exercise toggle_pause_all with
    # multiple workers on one account. Phase 4 default is False.
    sched = Scheduler(reg, concurrent_plugins=True)
    sched.register_account(_make_runtime("alice"))
    w1 = sched.start_plugin("looper", "alice")
    w2 = sched.start_plugin("looper_b", "alice")
    try:
        w1.plugin.run_started.wait(timeout=1.0)
        w2.plugin.run_started.wait(timeout=1.0)

        sched.toggle_pause_all()  # neither paused -> pause all
        assert w1.status == WorkerStatus.PAUSED
        assert w2.status == WorkerStatus.PAUSED

        sched.toggle_pause_all()  # some paused -> resume all
        time.sleep(0.05)
        assert w1.status == WorkerStatus.RUNNING
        assert w2.status == WorkerStatus.RUNNING
    finally:
        sched.stop_all(timeout=2.0)


def test_wait_for_idle_returns_when_done():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice"))
    sched.start_plugin("looper", "alice")
    sched.stop_all(timeout=2.0)
    assert sched.wait_for_idle(timeout=1.0) is True


def test_shutdown_stops_workers_and_dispatcher():
    reg = _make_registry(_LongLoopPlugin)
    sched = Scheduler(reg)
    sched.start()
    sched.register_account(_make_runtime("alice"))
    sched.start_plugin("looper", "alice")
    sched.shutdown()
    assert sched.list_status()["alice"]["looper"] == WorkerStatus.STOPPED
