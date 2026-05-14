"""Unit tests for `PluginWorker` lifecycle: start, pause, resume, stop, errors."""

from __future__ import annotations

import logging
import threading
import time

import pytest

from core.cache.manager import CacheManager
from core.exceptions import BotError, WorkerAlreadyRunning
from core.scheduler.plugin_base import GameplayPlugin, PluginContext
from core.scheduler.worker import PluginWorker, WorkerStatus


class _NoopGraph:
    """Stand-in for `GameGraph` — workers don't touch it directly."""


def _make_context(account_id: str = "test", extras=None) -> PluginContext:
    """Build a minimal `PluginContext` with stubs.

    Worker doesn't actually invoke navigator/backend/matcher in the unit
    tests, so we wire them with sentinel objects to avoid pulling in the
    full stack.
    """
    return PluginContext(
        account_id=account_id,
        backend=object(),         # type: ignore[arg-type]
        navigator=object(),       # type: ignore[arg-type]
        matcher=object(),         # type: ignore[arg-type]
        ocr=None,
        cache=CacheManager(account_id=account_id),
        logger=logging.getLogger(f"test.{account_id}"),
        extras=extras or {},
    )


class _CountingPlugin(GameplayPlugin):
    """Counts setup/teardown invocations; run loops until stop or N iters."""

    name = "counting"
    display_name = "Counting"

    def __init__(self, max_iters: int = 1000) -> None:
        super().__init__()
        self.setup_called = 0
        self.teardown_called = 0
        self.iters = 0
        self.max_iters = max_iters

    @classmethod
    def build_subgraph(cls):  # pragma: no cover — not used in these tests
        return _NoopGraph()  # type: ignore[return-value]

    def setup(self, ctx: PluginContext) -> None:
        self.setup_called += 1

    def run(self, ctx: PluginContext) -> None:
        while not ctx.should_stop() and self.iters < self.max_iters:
            self.iters += 1
            ctx.sleep(0.01)

    def teardown(self, ctx: PluginContext) -> None:
        self.teardown_called += 1


class _RaisingPlugin(GameplayPlugin):
    name = "raising"

    def __init__(self, where: str = "run", exc=None) -> None:
        super().__init__()
        self.where = where
        self.exc = exc or BotError("boom")
        self.teardown_called = 0

    @classmethod
    def build_subgraph(cls):  # pragma: no cover
        return _NoopGraph()  # type: ignore[return-value]

    def setup(self, ctx):
        if self.where == "setup":
            raise self.exc

    def run(self, ctx):
        if self.where == "run":
            raise self.exc

    def teardown(self, ctx):
        self.teardown_called += 1


def test_worker_initial_state():
    p = _CountingPlugin()
    w = PluginWorker(p, _make_context())
    assert w.status == WorkerStatus.IDLE
    assert w.last_error is None
    assert not w.is_alive()


def test_worker_start_run_stop_lifecycle():
    p = _CountingPlugin(max_iters=10000)
    w = PluginWorker(p, _make_context())
    w.start()
    # Give it a moment to enter run.
    time.sleep(0.05)
    assert w.is_alive()
    assert w.status == WorkerStatus.RUNNING

    ok = w.stop(timeout=2.0)
    assert ok, "worker should have stopped within timeout"
    assert w.status == WorkerStatus.STOPPED
    assert p.setup_called == 1
    assert p.teardown_called == 1
    assert p.iters > 0


def test_worker_pause_resume_flow():
    """pause() flips status to PAUSED; resume() returns it to RUNNING."""
    p = _CountingPlugin(max_iters=100_000)
    w = PluginWorker(p, _make_context())
    w.start()
    time.sleep(0.05)
    w.pause()
    assert w.status == WorkerStatus.PAUSED
    w.resume()
    # Give the worker thread a chance to register the resume.
    time.sleep(0.02)
    assert w.status in (WorkerStatus.RUNNING, WorkerStatus.STOPPED)
    w.stop(timeout=2.0)


def test_worker_double_start_raises():
    p = _CountingPlugin(max_iters=100_000)
    w = PluginWorker(p, _make_context())
    w.start()
    try:
        with pytest.raises(WorkerAlreadyRunning):
            w.start()
    finally:
        w.stop(timeout=2.0)


def test_worker_captures_boterror():
    p = _RaisingPlugin(where="run", exc=BotError("planned"))
    w = PluginWorker(p, _make_context())
    w.start()
    w.stop(timeout=2.0)  # join after run raises
    assert w.status == WorkerStatus.ERROR
    assert isinstance(w.last_error, BotError)
    assert "planned" in str(w.last_error)
    # teardown still runs even after run raised
    assert p.teardown_called == 1


def test_worker_captures_non_boterror():
    p = _RaisingPlugin(where="run", exc=KeyError("missing"))
    w = PluginWorker(p, _make_context())
    w.start()
    w.stop(timeout=2.0)
    assert w.status == WorkerStatus.ERROR
    assert isinstance(w.last_error, KeyError)
    assert p.teardown_called == 1


def test_worker_setup_failure_skips_run_but_still_tears_down():
    p = _RaisingPlugin(where="setup", exc=BotError("nope"))
    w = PluginWorker(p, _make_context())
    w.start()
    w.stop(timeout=2.0)
    assert w.status == WorkerStatus.ERROR
    assert isinstance(w.last_error, BotError)
    assert p.teardown_called == 1


def test_ctx_sleep_returns_true_on_stop():
    """ctx.sleep should return True when stop was signalled."""
    ctx = _make_context()
    # Simulate a worker: signal stop after a delay.
    stopper = threading.Timer(0.05, ctx._stop_event.set)
    stopper.start()
    t0 = time.monotonic()
    stopped = ctx.sleep(5.0)
    elapsed = time.monotonic() - t0
    stopper.join()
    assert stopped is True
    assert elapsed < 1.0, f"sleep took {elapsed}s; should have woken early"


def test_ctx_wait_until_resumed_unblocks_on_resume():
    ctx = _make_context()
    ctx._signal_pause() if hasattr(ctx, "_signal_pause") else ctx._pause_event.set()

    resumed = threading.Timer(0.05, ctx._pause_event.clear)
    resumed.start()
    t0 = time.monotonic()
    stop_signalled = ctx.wait_until_resumed(poll=0.02)
    elapsed = time.monotonic() - t0
    resumed.join()
    assert stop_signalled is False
    assert elapsed < 1.0


def test_worker_stop_when_never_started():
    """stop() before start() should be a no-op that still flips to STOPPED."""
    p = _CountingPlugin()
    w = PluginWorker(p, _make_context())
    ok = w.stop(timeout=1.0)
    assert ok
    # Status should transition from IDLE -> STOPPED so the scheduler can
    # discard the worker rather than block.
    assert w.status == WorkerStatus.STOPPED
