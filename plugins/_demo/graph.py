"""
`_demo` plugin subgraph: entry -> step1 -> step2.

Demonstrates:
    * Internal edges using bare names (auto-prefixed with `_demo.`).
    * A cross-namespace edge from `step2` back to the root `main_menu`. This
      is the canonical "return to main menu" pattern that real plugins use
      when their loop completes.
"""

from __future__ import annotations

from core.navigation import GameGraph, edge, external, subgraph, vertex
from graphs._demo_actions import demo_navigate, demo_recognizer


def build_subgraph() -> GameGraph:
    """Construct the `_demo` plugin subgraph (returns unmerged, internal namespace)."""
    with subgraph("_demo") as g:
        # Inside the context, bare names become `_demo.<name>`.
        vertex("entry", name="演示入口", recognizer=demo_recognizer("_demo.entry"))
        vertex("step1", name="演示第一步", recognizer=demo_recognizer("_demo.step1"))
        vertex("step2", name="演示第二步", recognizer=demo_recognizer("_demo.step2"))

        edge("entry", "step1", action=demo_navigate("_demo.step1"), cost=1.0)
        edge("step1", "step2", action=demo_navigate("_demo.step2"), cost=1.0)

        # Cross-namespace edge. "main_menu" lives in the root namespace
        # (no prefix), so a bare reference here would wrongly resolve to
        # `_demo.main_menu`. `external(...)` declares the absolute name.
        edge(
            "step2",
            external("main_menu"),
            action=demo_navigate("main_menu"),
            cost=1.5,
        )

    return g
