"""Unit tests for `HotkeyController` (noop backend)."""

from __future__ import annotations

import threading

import pytest

from core.hotkey.controller import HotkeyAction, HotkeyController


class _FakeScheduler:
    """Records calls; mimics the subset of Scheduler used by hotkeys."""

    def __init__(self):
        self.submitted = []
        self.stop_all_called = False

    def submit(self, callback):
        self.submitted.append(callback)
        callback()

    def stop_all(self, *, timeout=None):  # noqa: ARG002
        self.stop_all_called = True

    def toggle_pause_all(self, account_id=None):  # noqa: ARG002
        self.submitted.append("toggle")


def test_register_validates_inputs():
    sched = _FakeScheduler()
    ctrl = HotkeyController(sched, backend="noop")
    with pytest.raises(ValueError):
        ctrl.register("", lambda: None)
    with pytest.raises(ValueError):
        ctrl.register("f9", "not callable")  # type: ignore[arg-type]


def test_trigger_invokes_callback():
    sched = _FakeScheduler()
    ctrl = HotkeyController(sched, backend="noop")
    called = []
    ctrl.register("f1", lambda: called.append(True), description="x")
    ctrl.trigger("f1")
    assert called == [True]


def test_trigger_swallows_exceptions():
    sched = _FakeScheduler()
    ctrl = HotkeyController(sched, backend="noop")

    def boom():
        raise RuntimeError("nope")

    ctrl.register("f1", boom)
    # Should not raise out of trigger.
    ctrl.trigger("f1")


def test_register_defaults_wires_f9_f10():
    sched = _FakeScheduler()
    ctrl = HotkeyController(sched, backend="noop")
    ctrl.register_defaults()
    keys = {a.hotkey for a in ctrl.list()}
    assert {"f9", "f10", "f12"}.issubset(keys)

    # F9 should hit submit() which calls toggle_pause_all.
    ctrl.trigger("f9")
    assert "toggle" in sched.submitted

    # F10 should hit submit() which calls stop_all.
    ctrl.trigger("f10")
    assert sched.stop_all_called is True


def test_list_returns_sorted_snapshot():
    sched = _FakeScheduler()
    ctrl = HotkeyController(sched, backend="noop")
    ctrl.register("z", lambda: None)
    ctrl.register("a", lambda: None)
    keys = [a.hotkey for a in ctrl.list()]
    assert keys == ["a", "z"]


def test_re_register_replaces_callback():
    sched = _FakeScheduler()
    ctrl = HotkeyController(sched, backend="noop")
    calls = []
    ctrl.register("f1", lambda: calls.append("first"))
    ctrl.register("f1", lambda: calls.append("second"))
    ctrl.trigger("f1")
    assert calls == ["second"]


def test_start_stop_idempotent_on_noop():
    sched = _FakeScheduler()
    ctrl = HotkeyController(sched, backend="noop")
    ctrl.register("f1", lambda: None)
    ctrl.start()
    ctrl.start()  # idempotent
    ctrl.stop()
    ctrl.stop()  # idempotent


def test_unknown_backend_rejected():
    sched = _FakeScheduler()
    with pytest.raises(ValueError):
        HotkeyController(sched, backend="bogus")
