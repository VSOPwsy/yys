"""
Tests for the Phase 4 plugin error-recovery contract.

Covers:
    * `save_error_screenshot` writes a PNG to logs/<account>/error/.
    * `recover_to_main` returns the navigator goto result, swallows errors.
    * `handle_unexpected_error` retries up to MAX_RECOVERY_ATTEMPTS.
    * `PluginWorker` invokes the recovery hook after run() raises.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.cache.manager import CacheManager
from core.exceptions import NavigationError
from core.input_backend.fake import FakeBackend
from core.scheduler.plugin_base import GameplayPlugin, PluginContext
from core.scheduler.worker import PluginWorker, WorkerStatus


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class _ExplodingPlugin(GameplayPlugin):
    name = "boom"

    @classmethod
    def build_subgraph(cls):  # pragma: no cover
        from core.navigation.graph import GameGraph
        return GameGraph()

    def setup(self, ctx): pass
    def run(self, ctx): raise RuntimeError("boom from run()")
    def teardown(self, ctx): pass


def _make_ctx(*, navigator=None, backend=None, account_id="alice") -> PluginContext:
    return PluginContext(
        account_id=account_id,
        backend=backend or FakeBackend(account_id=account_id),
        navigator=navigator or MagicMock(),
        matcher=MagicMock(),
        ocr=None,
        cache=CacheManager(account_id=account_id),
        logger=logging.getLogger(f"test.{account_id}"),
    )


# --------------------------------------------------------------------------- #
# save_error_screenshot
# --------------------------------------------------------------------------- #
def test_save_error_screenshot_writes_png(tmp_path):
    plugin = _ExplodingPlugin()
    backend = MagicMock()
    backend.screenshot.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    ctx = _make_ctx(backend=backend)

    path = plugin.save_error_screenshot(
        ctx, RuntimeError("test exc"), log_root=tmp_path
    )
    assert path is not None
    assert path.exists()
    assert path.parent == tmp_path / "alice" / "error"


def test_save_error_screenshot_returns_none_on_backend_failure(tmp_path):
    plugin = _ExplodingPlugin()
    backend = MagicMock()
    backend.screenshot.side_effect = RuntimeError("backend dead")
    ctx = _make_ctx(backend=backend)
    path = plugin.save_error_screenshot(
        ctx, RuntimeError("test"), log_root=tmp_path
    )
    assert path is None


# --------------------------------------------------------------------------- #
# recover_to_main
# --------------------------------------------------------------------------- #
def test_recover_to_main_returns_navigator_result():
    nav = MagicMock()
    nav.goto.return_value = True
    plugin = _ExplodingPlugin()
    ctx = _make_ctx(navigator=nav)
    assert plugin.recover_to_main(ctx) is True
    nav.goto.assert_called_once_with(plugin.SAFE_VERTEX)


def test_recover_to_main_swallows_navigator_exception():
    nav = MagicMock()
    nav.goto.side_effect = NavigationError("can't find current screen")
    plugin = _ExplodingPlugin()
    ctx = _make_ctx(navigator=nav)
    assert plugin.recover_to_main(ctx) is False


# --------------------------------------------------------------------------- #
# handle_unexpected_error
# --------------------------------------------------------------------------- #
def test_handle_retries_up_to_max_attempts(monkeypatch, tmp_path):
    plugin = _ExplodingPlugin()
    plugin.MAX_RECOVERY_ATTEMPTS = 3

    attempts = []
    def fake_recover(ctx):
        attempts.append(1)
        return False
    plugin.recover_to_main = fake_recover  # type: ignore[assignment]

    # Skip the screenshot side-effect.
    plugin.save_error_screenshot = lambda *a, **kw: None  # type: ignore[assignment]

    ctx = _make_ctx()
    assert plugin.handle_unexpected_error(ctx, RuntimeError("x")) is False
    assert len(attempts) == 3


def test_handle_stops_on_first_success():
    plugin = _ExplodingPlugin()
    plugin.MAX_RECOVERY_ATTEMPTS = 3

    calls = []
    def fake_recover(ctx):
        calls.append(1)
        return True  # first attempt wins
    plugin.recover_to_main = fake_recover  # type: ignore[assignment]
    plugin.save_error_screenshot = lambda *a, **kw: None  # type: ignore[assignment]

    ctx = _make_ctx()
    assert plugin.handle_unexpected_error(ctx, RuntimeError("x")) is True
    assert len(calls) == 1


def test_handle_aborts_if_stop_requested():
    plugin = _ExplodingPlugin()
    plugin.MAX_RECOVERY_ATTEMPTS = 5
    plugin.recover_to_main = lambda ctx: False  # type: ignore[assignment]
    plugin.save_error_screenshot = lambda *a, **kw: None  # type: ignore[assignment]

    ctx = _make_ctx()
    ctx._stop_event.set()  # simulate operator-initiated stop

    assert plugin.handle_unexpected_error(ctx, RuntimeError("x")) is False


# --------------------------------------------------------------------------- #
# Worker integration: recovery is invoked after run() raises
# --------------------------------------------------------------------------- #
def test_worker_invokes_handle_unexpected_error_on_run_failure(monkeypatch):
    plugin = _ExplodingPlugin()
    plugin.AUTO_RECOVER_ON_UNEXPECTED_ERROR = True
    handler_seen = threading.Event()
    captured = {}

    def fake_handler(self, ctx, exc):
        captured["exc"] = exc
        handler_seen.set()
        return True
    plugin.handle_unexpected_error = fake_handler.__get__(plugin, type(plugin))  # type: ignore[assignment]

    ctx = _make_ctx()
    worker = PluginWorker(plugin, ctx)
    worker.start()
    assert handler_seen.wait(timeout=2.0)
    # Worker should still end in ERROR (run did raise) — recovery is best-effort.
    worker.stop(timeout=1.0)
    assert worker.status == WorkerStatus.ERROR
    assert isinstance(captured["exc"], RuntimeError)


def test_worker_skips_handler_when_auto_recover_disabled():
    plugin = _ExplodingPlugin()
    plugin.AUTO_RECOVER_ON_UNEXPECTED_ERROR = False
    called = []

    def fake_handler(self, ctx, exc):
        called.append(exc)
        return True
    plugin.handle_unexpected_error = fake_handler.__get__(plugin, type(plugin))  # type: ignore[assignment]

    ctx = _make_ctx()
    worker = PluginWorker(plugin, ctx)
    worker.start()
    worker.stop(timeout=1.0)
    assert called == []  # handler never invoked
    assert worker.status == WorkerStatus.ERROR
