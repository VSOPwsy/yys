"""`Navigator.goto(humanize=True)` should use random-path mode internally."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.exceptions import EdgeExecutionFailed
from core.navigation.graph import GameGraph
from core.navigation.navigator import Navigator
from core.navigation.pathfinder import PathFinder
from core.navigation.recognizer import ScreenRecognizer


def _make_graph_two_paths() -> GameGraph:
    """A diamond graph: a -> b -> d and a -> c -> d (two routes)."""
    g = GameGraph()
    for vid in ("a", "b", "c", "d"):
        g.add_vertex(vid, owner="main", dwell_time=0)
    g.add_edge("a", "b", action=lambda ctx: None, cost=1.0)
    g.add_edge("b", "d", action=lambda ctx: None, cost=1.0)
    g.add_edge("a", "c", action=lambda ctx: None, cost=1.0)
    g.add_edge("c", "d", action=lambda ctx: None, cost=1.0)
    return g


def test_humanize_kwarg_routes_through_random_mode():
    """When humanize=True, the navigator delegates to PathFinder.random_path."""
    g = _make_graph_two_paths()
    pf = PathFinder(g)
    # Stub random_path to always return a specific known route so the
    # recognizer assertions below are deterministic regardless of seed.
    edges_through_b = [g.get_edge("a", "b"), g.get_edge("b", "d")]
    pf.random_path = MagicMock(return_value=edges_through_b)
    pf.shortest_path = MagicMock(wraps=pf.shortest_path)

    backend = MagicMock()
    backend.screenshot.return_value = "shot"

    rec = MagicMock(spec=ScreenRecognizer)
    # detect_current is called: once for start vertex, once after each edge.
    rec.detect_current.side_effect = ["a", "b", "d"]

    nav = Navigator(backend=backend, graph=g, pathfinder=pf, recognizer=rec)
    assert nav.goto("d", humanize=True) is True
    assert pf.random_path.called
    # shortest_path is NOT used for the plan when humanize=True (we stubbed
    # random_path, so it can't have been called inside random_path either).
    pf.shortest_path.assert_not_called()


def test_humanize_false_stays_on_shortest():
    g = _make_graph_two_paths()
    pf = PathFinder(g)
    pf.random_path = MagicMock()
    pf.shortest_path = MagicMock(wraps=pf.shortest_path)

    backend = MagicMock()
    rec = MagicMock(spec=ScreenRecognizer)
    rec.detect_current.side_effect = ["a", "b", "d"]

    nav = Navigator(backend=backend, graph=g, pathfinder=pf, recognizer=rec)
    nav.goto("d")
    pf.random_path.assert_not_called()
    assert pf.shortest_path.called
