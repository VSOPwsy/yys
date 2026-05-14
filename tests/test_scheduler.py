"""Unit tests for `Scheduler`: registration, start/stop, command queue."""

from __future__ import annotations

import logging
import threading
import time
from typing import List

import pytest

from core.cache.manager import CacheManager
from core.exceptions import (
    AccountNotRegistered,
    PluginNotRegistered,
    PluginRequirementUnmet,
    WorkerAlreadyRunning,
)
from core.input_backend.fake import FakeBackend
from core.navigation import (
    GameGraph,
    GraphAssembler,
    Navigator,
    PathFinder,
    ScreenRecognizer,
    edge,
    external,
    root_graph,
    subgraph,
    vertex,
)
from core.scheduler.plugin_base import GameplayPlugin, PluginContext
from core.scheduler.registry import PluginRegistry
from core.scheduler.scheduler import AccountRuntime, Scheduler
from core.scheduler.worker import WorkerStatus


# --------------------------------------------------------------------------- #
# Test fixtures
# --------------------------------------------------------------------------- #
def _stub_recognizer(expected: str):
    def _matches(screenshot):
        return getattr(screenshot, "_demo_screen", None) == expected
    return _matches


def _stub_navigate(target: str):
    def _action(ctx):
        ctx.backend.current_screen = target
    return _action


def _build_root() -> GameGraph:
    with root_graph() as g:
        vertex("main_menu", recognizer=_stub_recognizer("main_menu"))
        vertex("home", recognizer=_stub_recognizer("home"))
        edge("main_menu", "home", action=_stub_navigate("home"), cost=1.0)
        edge("home", "main_menu", action=_stub_navigate("main_menu"), cost=1.0)
    return g


def _build_sub(namespace: str) -> GameGraph:
    with subgraph(namespace) as g:
        vertex("a", recognizer=_stub_recognizer(f"{namespace}.a"))
        vertex("b", recognizer=_stub_recognizer(f"{namespace}.b"))
        edge("a", "b", action=_stub_navigate(f"{namespace}.b"), cost=1.0)
        edge("b", external("main_menu"), action=_stub_navigate("main_menu"), cost=1.0)
    return g


def _assemble(namespace: str) -> GameGraph:
    asm = GraphAssembler()
    asm.set_main(_build_root())
    asm.add_subgraph(namespace, _build_sub(namespace))
    return asm.assemble(enabled_plugins={namespace})


class _ScriptPlugin(GameplayPlugin):
    """Records what `run()` did so we can assert on it."""

    name = "scripted"

    def __init__(self) -> None:
        super().__init__()
        self.events: List[str] = []
        self.iters = 0

    @classmethod
    def build_subgraph(cls):  # pragma: no cover — registered manually
        return _build_sub("scripted")

    def setup(self, ctx):
        self.events.append("setup")

    def run(self, ctx):
        self.events.append("run")
        while not ctx.should_stop():
            self.iters += 1
            if ctx.sleep(0.01):
                break

    def teardown(self, ctx):
        self.events.append("teardown")


class _RequiresPlugin(GameplayPlugin):
    name = "needs_unknown"
    requires_vertices = ["does_not_exist"]

    @classmethod
    def build_subgraph(cls):
        return _build_sub("needs_unknown")

    def setup(self, ctx): pass
    def run(self, ctx): pass
    def teardown(self, ctx): pass


def _make_runtime(account_id: str, plugin_namespace: str) -> AccountRuntime:
    """Build a complete AccountRuntime for the scripted plugin's namespace."""
    backend = FakeBackend("main_menu", account_id=account_id)
    backend.connect()
    graph = _assemble(plugin_namespace)
    navigator = Navigator(
        backend=backend,
        graph=graph,
        pathfinder=PathFinder(graph),
        recognizer=ScreenRecognizer(matcher=backend.matcher),
    )
    return AccountRuntime(
        account_id=account_id,
        backend=backend,
        graph=graph,
        navigator=navigator,
        matcher=backend.matcher,
        cache=CacheManager(account_id=account_id),
        ocr=None,
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_register_unregister_account():
    reg = PluginRegistry()
    sched = Scheduler(reg)
    rt = _make_runtime("alice", "scripted")
    sched.register_account(rt)
    assert "alice" in sched.registered_accounts()
    sched.unregister_account("alice")
    assert "alice" not in sched.registered_accounts()


def test_start_unknown_plugin_raises():
    reg = PluginRegistry()
    sched = Scheduler(reg)
    rt = _make_runtime("alice", "scripted")
    sched.register_account(rt)
    with pytest.raises(PluginNotRegistered):
        sched.start_plugin("ghost", "alice")


def test_start_unknown_account_raises():
    reg = PluginRegistry()
    reg.register(_ScriptPlugin)
    sched = Scheduler(reg)
    with pytest.raises(AccountNotRegistered):
        sched.start_plugin("scripted", "nobody")


def test_requires_vertices_pre_flight():
    reg = PluginRegistry()
    reg.register(_RequiresPlugin)
    sched = Scheduler(reg)
    # Build runtime using a graph that does NOT include "does_not_exist".
    rt = _make_runtime("alice", "needs_unknown")
    sched.register_account(rt)
    with pytest.raises(PluginRequirementUnmet):
        sched.start_plugin("needs_unknown", "alice")


def test_start_pause_resume_stop_round_trip():
    reg = PluginRegistry()
    reg.register(_ScriptPlugin)
    sched = Scheduler(reg)
    rt = _make_runtime("alice", "scripted")
    sched.register_account(rt)

    worker = sched.start_plugin("scripted", "alice")
    time.sleep(0.05)
    assert worker.status == WorkerStatus.RUNNING

    sched.pause_plugin("scripted", "alice")
    assert worker.status == WorkerStatus.PAUSED

    sched.resume_plugin("scripted", "alice")
    time.sleep(0.02)
    assert worker.status in (WorkerStatus.RUNNING, WorkerStatus.STOPPED)

    ok = sched.stop_plugin("scripted", "alice", timeout=2.0)
    assert ok
    assert worker.status == WorkerStatus.STOPPED


def test_start_same_pair_twice_raises():
    reg = PluginRegistry()
    reg.register(_ScriptPlugin)
    sched = Scheduler(reg)
    rt = _make_runtime("alice", "scripted")
    sched.register_account(rt)

    sched.start_plugin("scripted", "alice")
    try:
        with pytest.raises(WorkerAlreadyRunning):
            sched.start_plugin("scripted", "alice")
    finally:
        sched.stop_plugin("scripted", "alice")


def test_list_status_snapshot():
    reg = PluginRegistry()
    reg.register(_ScriptPlugin)
    sched = Scheduler(reg)
    rt = _make_runtime("alice", "scripted")
    sched.register_account(rt)
    sched.start_plugin("scripted", "alice")
    try:
        snap = sched.list_status()
        assert "alice" in snap
        assert snap["alice"]["scripted"] in (WorkerStatus.RUNNING, WorkerStatus.PAUSED)
    finally:
        sched.stop_plugin("scripted", "alice")


def test_command_queue_dispatches_callables():
    reg = PluginRegistry()
    sched = Scheduler(reg)
    sched.start()
    try:
        events: List[str] = []
        sched.submit(lambda: events.append("a"))
        sched.submit(lambda: events.append("b"))
        sched.submit(lambda: events.append("c"))
        deadline = time.monotonic() + 1.0
        while len(events) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert events == ["a", "b", "c"]
    finally:
        sched.shutdown()


def test_command_queue_swallows_exceptions():
    reg = PluginRegistry()
    sched = Scheduler(reg)
    sched.start()
    try:
        events: List[str] = []
        sched.submit(lambda: events.append("before"))
        sched.submit(lambda: (_ for _ in ()).throw(RuntimeError("oops")))
        sched.submit(lambda: events.append("after"))
        deadline = time.monotonic() + 1.0
        while len(events) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        # The dispatcher should keep going past the failed command.
        assert events == ["before", "after"]
    finally:
        sched.shutdown()


def test_shutdown_stops_workers_and_dispatcher():
    reg = PluginRegistry()
    reg.register(_ScriptPlugin)
    sched = Scheduler(reg)
    rt = _make_runtime("alice", "scripted")
    sched.register_account(rt)
    sched.start()
    sched.start_plugin("scripted", "alice")
    time.sleep(0.05)
    sched.shutdown()
    statuses = sched.list_status()
    assert statuses["alice"]["scripted"] == WorkerStatus.STOPPED


def test_per_account_workers_are_isolated():
    reg = PluginRegistry()
    reg.register(_ScriptPlugin)
    sched = Scheduler(reg)
    sched.register_account(_make_runtime("alice", "scripted"))
    sched.register_account(_make_runtime("bob", "scripted"))
    a = sched.start_plugin("scripted", "alice")
    b = sched.start_plugin("scripted", "bob")
    try:
        time.sleep(0.05)
        # Stopping alice shouldn't touch bob.
        sched.stop_plugin("scripted", "alice", timeout=1.0)
        assert a.status == WorkerStatus.STOPPED
        assert b.status in (WorkerStatus.RUNNING, WorkerStatus.PAUSED)
    finally:
        sched.stop_plugin("scripted", "bob", timeout=2.0)


def test_wait_for_idle_returns_when_all_stopped():
    reg = PluginRegistry()
    reg.register(_ScriptPlugin)
    sched = Scheduler(reg)
    rt = _make_runtime("alice", "scripted")
    sched.register_account(rt)
    worker = sched.start_plugin("scripted", "alice")
    threading.Timer(0.05, lambda: sched.stop_plugin("scripted", "alice")).start()
    assert sched.wait_for_idle(timeout=2.0) is True
    assert worker.status == WorkerStatus.STOPPED
