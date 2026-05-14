"""
`_demo` plugin subgraph: demo_screen_1 <-> demo_screen_2 -> main_menu.

Demonstrates:
    * Internal edges using bare names (auto-prefixed with `_demo.`).
    * A cross-namespace edge from `demo_screen_2` back to the root
      `main_menu`. This is the canonical "return to main menu" pattern
      that real plugins use when their loop completes.

The actions and recognizers are *fakes* (see `graphs/_demo_actions`) so
the demo can run against a `FakeBackend` without real templates. A real
plugin would point recognizers at `buttons.py` Buttons and edge actions
at `click_button(...)`.
"""

from __future__ import annotations

from core.navigation import GameGraph, edge, external, subgraph, vertex
from graphs._demo_actions import demo_navigate, demo_recognizer


def build_subgraph() -> GameGraph:
    """Construct the `_demo` plugin subgraph (returns unmerged)."""
    with subgraph("_demo") as g:
        # Inside the context, bare names become `_demo.<name>`.
        vertex(
            "demo_screen_1",
            name="演示界面 1",
            recognizer=demo_recognizer("_demo.demo_screen_1"),
        )
        vertex(
            "demo_screen_2",
            name="演示界面 2",
            recognizer=demo_recognizer("_demo.demo_screen_2"),
        )

        # Two-way edge between the demo's own screens.
        edge(
            "demo_screen_1", "demo_screen_2",
            action=demo_navigate("_demo.demo_screen_2"),
            cost=1.0,
        )
        edge(
            "demo_screen_2", "demo_screen_1",
            action=demo_navigate("_demo.demo_screen_1"),
            cost=1.0,
        )

        # Cross-namespace return edge: out of the plugin, back into root.
        # `main_menu` lives in the root namespace (no prefix), so a bare
        # reference would wrongly resolve to `_demo.main_menu`.
        # `external(...)` declares the absolute name.
        edge(
            "demo_screen_2",
            external("main_menu"),
            action=demo_navigate("main_menu"),
            cost=1.5,
        )

    return g
