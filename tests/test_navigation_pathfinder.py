"""PathFinder: shortest, random, avoid_risky / avoid_tags filtering."""

from __future__ import annotations

import random

import pytest

from core.exceptions import NoPathFound, UnknownVertex
from core.navigation import GameGraph, PathFinder


def _no_action(_ctx):  # noqa: ANN001
    pass


def _diamond() -> GameGraph:
    """A -> B -> D; A -> C -> D. Two equal-length paths."""
    g = GameGraph()
    for n in "ABCD":
        g.add_vertex(n)
    g.add_edge("A", "B", action=_no_action, cost=1.0)
    g.add_edge("B", "D", action=_no_action, cost=1.0)
    g.add_edge("A", "C", action=_no_action, cost=1.0)
    g.add_edge("C", "D", action=_no_action, cost=1.0)
    return g


def test_shortest_path_basic():
    g = _diamond()
    pf = PathFinder(g)
    path = pf.shortest_path("A", "D")
    assert len(path) == 2
    assert path[0].src == "A" and path[-1].dst == "D"


def test_shortest_path_same_vertex_is_empty():
    g = _diamond()
    pf = PathFinder(g)
    assert pf.shortest_path("A", "A") == []


def test_unknown_vertex_raises():
    g = _diamond()
    pf = PathFinder(g)
    with pytest.raises(UnknownVertex):
        pf.shortest_path("A", "Z")
    with pytest.raises(UnknownVertex):
        pf.shortest_path("Z", "A")


def test_no_path_found():
    g = GameGraph()
    g.add_vertex("A")
    g.add_vertex("B")
    pf = PathFinder(g)
    with pytest.raises(NoPathFound):
        pf.shortest_path("A", "B")


def test_avoid_risky_routes_around_risky_edge():
    g = GameGraph()
    g.add_vertex("A")
    g.add_vertex("B")
    g.add_vertex("D")
    # Direct risky edge (cheap) vs detour via B (slightly more expensive).
    g.add_edge("A", "D", action=_no_action, cost=1.0, risky=True)
    g.add_edge("A", "B", action=_no_action, cost=1.0)
    g.add_edge("B", "D", action=_no_action, cost=1.0)
    pf = PathFinder(g)
    risky_path = pf.shortest_path("A", "D")
    assert len(risky_path) == 1 and risky_path[0].risky
    safe_path = pf.shortest_path("A", "D", avoid_risky=True)
    assert len(safe_path) == 2
    assert not any(e.risky for e in safe_path)


def test_avoid_tags_filters_correctly():
    g = GameGraph()
    g.add_vertex("A")
    g.add_vertex("B")
    g.add_vertex("D")
    g.add_edge("A", "D", action=_no_action, cost=1.0, tags=["advertise"])
    g.add_edge("A", "B", action=_no_action, cost=1.0)
    g.add_edge("B", "D", action=_no_action, cost=1.0)
    pf = PathFinder(g)
    path = pf.shortest_path("A", "D", avoid_tags=["advertise"])
    assert len(path) == 2


def test_no_path_when_all_routes_banned():
    g = GameGraph()
    g.add_vertex("A")
    g.add_vertex("D")
    g.add_edge("A", "D", action=_no_action, risky=True)
    pf = PathFinder(g)
    with pytest.raises(NoPathFound):
        pf.shortest_path("A", "D", avoid_risky=True)


def test_random_path_can_pick_either_route():
    """With two equal paths, repeated calls should not always return the same."""
    g = _diamond()
    pf = PathFinder(g)
    seen = set()
    rng = random.Random(0)
    for _ in range(50):
        path = pf.random_path("A", "D", rng=rng)
        seen.add(tuple((e.src, e.dst) for e in path))
    # Both paths should have been picked at least once with a deterministic seed.
    assert len(seen) >= 2


def test_random_path_returns_valid_path_with_constraints():
    """When avoid_tags drops one route, random_path still returns the other."""
    g = GameGraph()
    for n in "ABCD":
        g.add_vertex(n)
    g.add_edge("A", "B", action=_no_action, cost=1.0)
    g.add_edge("B", "D", action=_no_action, cost=1.0)
    g.add_edge("A", "C", action=_no_action, cost=1.0, tags=["advertise"])
    g.add_edge("C", "D", action=_no_action, cost=1.0)
    pf = PathFinder(g)
    path = pf.random_path("A", "D", avoid_tags=["advertise"])
    # Must take A->B->D since A->C is banned.
    assert [(e.src, e.dst) for e in path] == [("A", "B"), ("B", "D")]


def test_all_paths_enumerates_all_simple():
    g = _diamond()
    pf = PathFinder(g)
    paths = pf.all_paths("A", "D")
    assert len(paths) == 2
    assert all(len(p) == 2 for p in paths)


def test_pathfinder_validates_random_path_args():
    g = _diamond()
    pf = PathFinder(g)
    with pytest.raises(ValueError):
        pf.random_path("A", "D", max_paths=0)
    with pytest.raises(ValueError):
        pf.random_path("A", "D", max_length_factor=0.5)
