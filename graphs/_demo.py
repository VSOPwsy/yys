"""
Demo root graph used by `main.py` to validate Phase 2 end-to-end.

Three vertices (main_menu, profile, settings) and a couple of edges between
them. Recognizers are callables that read a string from the supplied
`FakeBackend` so we can run the whole stack without a live emulator. Real
deployments will swap these for `Button` templates.

This module is intentionally tiny — its job is to exercise the merge +
cross-namespace edge path, not to ship a real game graph.
"""

from __future__ import annotations

from core.navigation import (
    GameGraph,
    click_at,
    edge,
    root_graph,
    vertex,
    wait,
)
from graphs._demo_actions import demo_navigate, demo_recognizer


def build_main_graph() -> GameGraph:
    """Construct the root (no-namespace) graph for the demo."""
    with root_graph() as g:
        vertex(
            "main_menu",
            name="主菜单",
            recognizer=demo_recognizer("main_menu"),
        )
        vertex(
            "profile",
            name="个人信息",
            recognizer=demo_recognizer("profile"),
        )
        vertex(
            "settings",
            name="设置",
            recognizer=demo_recognizer("settings"),
        )

        edge(
            "main_menu", "profile",
            action=demo_navigate("profile"),
            cost=1.0,
        )
        edge(
            "profile", "main_menu",
            action=demo_navigate("main_menu"),
            cost=0.8,
        )
        edge(
            "main_menu", "settings",
            action=demo_navigate("settings"),
            cost=1.0,
        )
        edge(
            "settings", "main_menu",
            action=demo_navigate("main_menu"),
            cost=0.8,
        )

        # Entry into the _demo plugin. We declare this in the *main* graph
        # because main owns "main_menu" — the plugin only owns its own
        # vertices and can't add edges originating from main's territory.
        edge(
            "main_menu", "_demo.entry",
            action=demo_navigate("_demo.entry"),
            cost=1.2,
        )

    return g
