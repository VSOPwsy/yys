"""
Phase 2 demo entry point.

What it does
------------
* Builds the root demo graph and the `_demo` plugin subgraph.
* Assembles them via `GraphAssembler` (only `_demo` is enabled).
* Wires a `FakeBackend` whose "screen" is a string we mutate to simulate
  state transitions. Recognizers read the same string.
* Navigates main_menu -> _demo.step2, then back to main_menu using the
  plugin's cross-namespace return edge.

This proves the Phase 2 wiring without needing a live emulator. Replace
`FakeBackend` with `NemuIpcBackend` (and the demo actions with real
clicks) to run on a real game.

Run::

    D:\anaconda3\envs\yys\python.exe main.py
"""

from __future__ import annotations

import numpy as np

from core.input_backend.base import InputBackend
from core.logging_config import setup_logging, get_logger
from core.navigation import GraphAssembler, Navigator, PathFinder, ScreenRecognizer
from graphs._demo import build_main_graph
from plugins._demo.graph import build_subgraph as build_demo_subgraph

log = get_logger(__name__)


class _Frame(np.ndarray):
    """ndarray subclass that carries a string tag for demo recognizers.

    The recognizer reads `frame._demo_screen`. A real backend returns a
    plain BGR ndarray; this subclass lets us look like one while smuggling
    the synthetic "which screen am I on?" tag through.
    """

    def __new__(cls, screen_id: str):
        obj = np.zeros((4, 4, 3), dtype=np.uint8).view(cls)
        obj._demo_screen = screen_id
        return obj


class FakeBackend(InputBackend):
    """Minimal `InputBackend` that simulates an emulator with one string variable.

    The demo actions (`graphs/_demo_actions.demo_navigate`) write to
    `self.current_screen`; the recognizers read it back. No clicks, no
    swipes, no IPC — just enough plumbing to put `Navigator` through its
    paces.
    """

    def __init__(self, initial_screen: str = "main_menu") -> None:
        super().__init__(account_id="demo")
        self.current_screen = initial_screen
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def screenshot(self):
        return _Frame(self.current_screen)

    def click_xy(self, x: int, y: int, randomize: bool = True) -> None:
        log.debug("FakeBackend.click_xy(%d, %d) -- demo no-op", x, y)

    def long_click_xy(self, x, y, duration):
        if duration <= 0:
            raise ValueError("duration must be > 0")

    def swipe(self, p1, p2, duration):
        if duration <= 0:
            raise ValueError("duration must be > 0")

    def drag(self, p1, p2, duration):
        if duration <= 0:
            raise ValueError("duration must be > 0")


def main() -> None:
    setup_logging()

    asm = GraphAssembler()
    asm.set_main(build_main_graph())
    asm.add_subgraph("_demo", build_demo_subgraph())
    graph = asm.assemble(enabled_plugins={"_demo"})
    log.info("assembled graph: %s", graph)

    with FakeBackend("main_menu") as backend:
        nav = Navigator(
            backend=backend,
            graph=graph,
            pathfinder=PathFinder(graph),
            recognizer=ScreenRecognizer(matcher=backend.matcher),
        )

        log.info("--- goto _demo.step2 ---")
        nav.goto("_demo.step2")
        assert backend.current_screen == "_demo.step2", backend.current_screen

        log.info("--- goto main_menu (uses cross-namespace edge) ---")
        nav.goto("main_menu")
        assert backend.current_screen == "main_menu", backend.current_screen

    log.info("demo complete")


if __name__ == "__main__":
    main()
