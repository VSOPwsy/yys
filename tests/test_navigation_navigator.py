"""Navigator: end-to-end goto() with a synthetic backend + cross-namespace path."""

from __future__ import annotations

import numpy as np
import pytest

from core.exceptions import (
    CurrentVertexUnknown,
    EdgeExecutionFailed,
    UnknownVertex,
)
from core.input_backend.base import InputBackend
from core.navigation import (
    GraphAssembler,
    Navigator,
    ScreenRecognizer,
    edge,
    external,
    root_graph,
    subgraph,
    vertex,
)


# --------------------------------------------------------------------------- #
# Synthetic backend: holds a single "screen name" we can assert against.
# --------------------------------------------------------------------------- #
class _ScreenFrame(np.ndarray):
    """ndarray that smuggles a screen id through to recognizers."""
    def __new__(cls, screen_id: str):
        obj = np.zeros((4, 4, 3), dtype=np.uint8).view(cls)
        obj._screen = screen_id
        return obj


class _FakeBackend(InputBackend):
    def __init__(self, initial: str = "main_menu"):
        super().__init__(account_id="test")
        self.current = initial
        self.actions_run: list[str] = []
        # Some tests flip this to force action failures (no screen change).
        self.allow_transition = True
        self._connected = False

    def connect(self): self._connected = True
    def disconnect(self): self._connected = False
    def is_connected(self): return self._connected

    def screenshot(self):
        return _ScreenFrame(self.current)

    def click_xy(self, x, y, randomize=True): pass
    def long_click_xy(self, x, y, duration):
        if duration <= 0: raise ValueError
    def swipe(self, p1, p2, duration):
        if duration <= 0: raise ValueError
    def drag(self, p1, p2, duration):
        if duration <= 0: raise ValueError


def _recognizer_for(screen_id: str):
    def matches(shot):
        return getattr(shot, "_screen", None) == screen_id
    matches.__name__ = f"is_{screen_id}"
    return matches


def _go_to(target: str):
    """Action factory: deterministically sets backend.current to `target`."""
    def _action(ctx):
        ctx.backend.current = target
        ctx.backend.actions_run.append(target)
    _action.__name__ = f"go_to({target})"
    return _action


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def _build_test_graph():
    """root: main_menu, profile. plugin: entry, exit (returns to main_menu)."""
    with root_graph() as main:
        vertex("main_menu", recognizer=_recognizer_for("main_menu"))
        vertex("profile", recognizer=_recognizer_for("profile"))
        edge("main_menu", "profile", action=_go_to("profile"), cost=1)
        edge("profile", "main_menu", action=_go_to("main_menu"), cost=1)
        edge("main_menu", "plugin.entry", action=_go_to("plugin.entry"), cost=1)
    with subgraph("plugin") as sub:
        vertex("entry", recognizer=_recognizer_for("plugin.entry"))
        vertex("exit", recognizer=_recognizer_for("plugin.exit"))
        edge("entry", "exit", action=_go_to("plugin.exit"), cost=1)
        edge("exit", external("main_menu"), action=_go_to("main_menu"), cost=1)
    asm = GraphAssembler()
    asm.set_main(main)
    asm.add_subgraph("plugin", sub)
    return asm.assemble(enabled_plugins={"plugin"})


def test_goto_simple_path():
    graph = _build_test_graph()
    backend = _FakeBackend("main_menu")
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend:
        assert nav.goto("profile") is True
    assert backend.current == "profile"
    assert backend.actions_run == ["profile"]


def test_goto_cross_namespace_path():
    graph = _build_test_graph()
    backend = _FakeBackend("main_menu")
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend:
        nav.goto("plugin.exit")
    assert backend.current == "plugin.exit"
    assert backend.actions_run == ["plugin.entry", "plugin.exit"]


def test_goto_back_via_cross_namespace_edge():
    graph = _build_test_graph()
    backend = _FakeBackend("plugin.exit")
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend:
        nav.goto("main_menu")
    assert backend.current == "main_menu"
    assert backend.actions_run == ["main_menu"]


def test_goto_already_at_target_is_noop():
    graph = _build_test_graph()
    backend = _FakeBackend("profile")
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend:
        assert nav.goto("profile") is True
    assert backend.actions_run == []


def test_goto_raises_when_current_unknown():
    graph = _build_test_graph()
    backend = _FakeBackend("???")  # no vertex recognizes this
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend, pytest.raises(CurrentVertexUnknown):
        nav.goto("profile")


def test_goto_raises_on_unknown_target():
    graph = _build_test_graph()
    backend = _FakeBackend("main_menu")
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend, pytest.raises(UnknownVertex):
        nav.goto("nonexistent")


def test_goto_replans_on_missed_edge():
    """If an edge action runs but doesn't change the screen, Navigator must
    not declare success — it should replan, and (because the action keeps
    failing) eventually raise EdgeExecutionFailed."""
    # Build a graph whose main_menu->profile action only changes the screen
    # when backend.allow_transition is True. We keep it False to force
    # repeated misses.
    def _flaky_go_to(target):
        def _action(ctx):
            if ctx.backend.allow_transition:
                ctx.backend.current = target
        _action.__name__ = f"flaky_go_to({target})"
        return _action

    with root_graph() as main:
        vertex("main_menu", recognizer=_recognizer_for("main_menu"))
        vertex("profile", recognizer=_recognizer_for("profile"))
        edge("main_menu", "profile", action=_flaky_go_to("profile"), cost=1)

    asm = GraphAssembler()
    asm.set_main(main)
    graph = asm.assemble()

    backend = _FakeBackend("main_menu")
    backend.allow_transition = False
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend, pytest.raises(EdgeExecutionFailed):
        nav.goto("profile", max_path_replans=1)


def test_is_at_handles_bare_and_qualified():
    graph = _build_test_graph()
    backend = _FakeBackend("main_menu")
    nav = Navigator(backend=backend, graph=graph,
                    recognizer=ScreenRecognizer())
    with backend:
        assert nav.is_at("main_menu") is True
        assert nav.is_at("profile") is False
        assert nav.is_at("plugin.entry") is False
