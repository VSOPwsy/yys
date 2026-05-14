"""Unit tests for `PluginWorker` lifecycle (start/stop/pause/resume/errors)."""

from __future__ import annotations

import logging
import threading
import time

import pytest

from core.exceptions import BotError, WorkerAlreadyRunning
from core.scheduler.plugin_base import GameplayPlugin, PluginContext
from core.scheduler.worker import PluginWorker, WorkerStatus


class _DummyGraph:
    """Minimal stand-in so `PluginContext` is happy without a real GameGraph."""

    def has_vertex(self, _vid):
        return True


def _make_ctx(account_id: str = "test") -> PluginContext:
    """Return a `PluginContext` with everything mocked to None/Mock."""
    return PluginContext(
        account_id=account_id,
        backend=None,  # type: ignore[arg-type]
        navigator=None,  # type: ignore[arg-type]
        matcher=None,  # type: ignore[arg-type]
        ocr=None,
        cache=None,  # type: ignore[arg-type]
        logger=logging.getLogger(f"test.{account_id}"),
    )


class _CountingPlugin(GameplayPlugin):
    """Plugin that increments a counter every poll until stop signalled."""

    name = "counting"
    requires_vertices = []

    @classmethod
    def build_subgraph(cls):  # pragma: no cover — unused
        from core.navigation.graph import GameGraph
        return GameGraph()

    def __init__(self):
        super().__init__()
        self.setup_calls = 0
        self.teardown_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.iterations = 0
        self.run_started = threading.Event()

    def setup(self, ctx):
        self.setup_calls += 1

    def run(self, ctx):
        self.run_started.set()
        while not ctx.should_stop():
            self.iterations += 1
            if ctx.should_pause():
                ctx.wait_until_resumed(poll=0.02)
                continue
            if ctx.sleep(0.01):
                return

    def teardown(self, ctx):
        self.teardown_calls += 1

    def on_pause(self, ctx):
        self.pause_calls += 1

    def on_resume(self, ctx):
        self.resume_calls += 1


class _RaisingPlugin(GameplayPlugin):
    name = "raiser"
    requires_vertices = []

    @classmethod
    def build_subgraph(cls):  # pragma: no cover
        from core.navigation.graph import GameGraph
        return GameGraph()

    def setup(self, ctx):
        pass

    def run(self, ctx):
        raise BotError("intentional failure")

    def teardown(self, ctx):
        pass


class _RaisingSetupPlugin(GameplayPlugin):
    name = "raiser_setup"
    requires_vertices = []

    @classmethod
    def build_subgraph(cls):  # pragma: no cover
        from core.navigation.graph import GameGraph
        return GameGraph()

    def setup(self, ctx):
        raise BotError("setup blew up")

    def run(self, ctx):  # pragma: no cover — never reached
        pass

    def teardown(self, ctx):
        pass


class _NonBotErrorPlugin(GameplayPlugin):
    name = "raiser_nonbot"
    requires_vertices = []

    @classmethod
    def build_subgraph(cls):  # pragma: no cover
        from core.navigation.graph import GameGraph
        return GameGraph()

    def setup(self, ctx):
        pass

    def run(self, ctx):
        raise KeyError("missing key")  # NOT a BotError

    def teardown(self, ctx):
        pass


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_worker_starts_runs_stops_cleanly():
    plugin = _CountingPlugin()
    worker = PluginWorker(plugin, _make_ctx())
    assert worker.status == WorkerStatus.IDLE

    worker.start()
    assert plugin.run_started.wait(timeout=1.0)
    assert worker.status == WorkerStatus.RUNNING

    assert worker.stop(timeout=2.0)
    assert worker.status == WorkerStatus.STOPPED
    assert plugin.setup_calls == 1
    assert plugin.teardown_calls == 1
    assert plugin.iterations >= 1


def test_pause_and_resume_toggle_state():
    plugin = _CountingPlugin()
    worker = PluginWorker(plugin, _make_ctx())
    worker.start()
    plugin.run_started.wait(timeout=1.0)

    worker.pause()
    assert worker.status == WorkerStatus.PAUSED
    assert plugin.pause_calls == 1
    iter_at_pause = plugin.iterations
    time.sleep(0.05)
    # While paused, the worker loops in wait_until_resumed which increments
    # iterations on the next outer-loop check; allow some movement.
    assert worker.status == WorkerStatus.PAUSED

    worker.resume()
    assert plugin.resume_calls == 1
    time.sleep(0.05)
    assert worker.status == WorkerStatus.RUNNING
    worker.stop(timeout=2.0)
    assert plugin.iterations > iter_at_pause


def test_double_start_raises():
    plugin = _CountingPlugin()
    worker = PluginWorker(plugin, _make_ctx())
    worker.start()
    try:
        with pytest.raises(WorkerAlreadyRunning):
            worker.start()
    finally:
        worker.stop(timeout=2.0)


def test_run_error_captured_in_last_error():
    plugin = _RaisingPlugin()
    worker = PluginWorker(plugin, _make_ctx())
    worker.start()
    # Run raises immediately; wait for thread to finish.
    deadline = time.monotonic() + 2.0
    while worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not worker.is_alive()
    assert worker.status == WorkerStatus.ERROR
    assert isinstance(worker.last_error, BotError)


def test_setup_error_skips_run_but_runs_teardown():
    class _TrackingTeardown(_RaisingSetupPlugin):
        teardown_called = False

        def teardown(self, ctx):
            type(self).teardown_called = True

    worker = PluginWorker(_TrackingTeardown(), _make_ctx())
    worker.start()
    deadline = time.monotonic() + 2.0
    while worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker.status == WorkerStatus.ERROR
    assert isinstance(worker.last_error, BotError)
    assert _TrackingTeardown.teardown_called is True


def test_non_bot_error_also_lands_in_error():
    worker = PluginWorker(_NonBotErrorPlugin(), _make_ctx())
    worker.start()
    deadline = time.monotonic() + 2.0
    while worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker.status == WorkerStatus.ERROR
    assert isinstance(worker.last_error, KeyError)


def test_restart_after_stop_succeeds():
    plugin = _CountingPlugin()
    worker = PluginWorker(plugin, _make_ctx())
    worker.start()
    plugin.run_started.wait(timeout=1.0)
    worker.stop(timeout=2.0)

    # Reset the event so the new cycle's run() can flip it again.
    plugin.run_started.clear()
    worker.start()
    assert plugin.run_started.wait(timeout=1.0)
    assert worker.status == WorkerStatus.RUNNING
    worker.stop(timeout=2.0)
    assert plugin.setup_calls == 2
    assert plugin.teardown_calls == 2
