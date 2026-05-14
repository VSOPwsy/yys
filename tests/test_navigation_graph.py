"""GameGraph: vertex/edge mutation, merge semantics, validate()."""

from __future__ import annotations

import pytest

from core.exceptions import GraphValidationError, UnknownVertex
from core.navigation.graph import GameGraph


def _no_action(_ctx):  # noqa: ANN001
    pass


def test_add_vertex_and_lookup():
    g = GameGraph()
    g.add_vertex("main_menu", name="主菜单", owner="main")
    v = g.get_vertex("main_menu")
    assert v.id == "main_menu"
    assert v.name == "主菜单"
    assert v.owner == "main"
    assert g.has_vertex("main_menu")
    assert "main_menu" in g


def test_duplicate_vertex_rejected():
    g = GameGraph()
    g.add_vertex("x")
    with pytest.raises(GraphValidationError):
        g.add_vertex("x")


def test_add_edge_creates_ghost_endpoint():
    """An edge to a not-yet-defined vertex should NOT crash; the missing
    endpoint stays as a ghost node until validate() decides what to do."""
    g = GameGraph()
    g.add_vertex("a")
    g.add_edge("a", "b", action=_no_action)
    assert g.has_edge("a", "b")
    # 'b' is in the underlying nx graph as a ghost — but `vertices()` skips it.
    assert "b" not in [v.id for v in g.vertices()]


def test_validate_drops_dangling_edges_with_warning(caplog):
    g = GameGraph()
    g.add_vertex("a")
    g.add_edge("a", "missing", action=_no_action)
    with caplog.at_level("WARNING"):
        dangling = g.validate(strict=False)
    assert len(dangling) == 1
    assert not g.has_edge("a", "missing")


def test_validate_strict_raises():
    g = GameGraph()
    g.add_vertex("a")
    g.add_edge("a", "missing", action=_no_action)
    with pytest.raises(GraphValidationError):
        g.validate(strict=True)


def test_merge_qualified_vertices():
    sub = GameGraph()
    sub.add_vertex("plugin.entry")
    sub.add_vertex("plugin.exit")
    sub.add_edge("plugin.entry", "plugin.exit", action=_no_action)

    main = GameGraph()
    main.add_vertex("main_menu", owner="main")
    main.merge(sub, namespace="plugin")

    assert main.has_vertex("plugin.entry")
    assert main.has_vertex("plugin.exit")
    assert main.vertex_owner("plugin.entry") == "plugin"


def test_merge_keeps_cross_namespace_edges_verbatim():
    """A subgraph edge that already references the root namespace should
    survive merge unchanged."""
    sub = GameGraph()
    sub.add_vertex("plugin.entry")
    # Cross-namespace edge: endpoint is in the root namespace, no prefix.
    sub.add_edge("plugin.entry", "main_menu", action=_no_action)

    main = GameGraph()
    main.add_vertex("main_menu", owner="main")
    main.merge(sub, namespace="plugin")

    assert main.has_edge("plugin.entry", "main_menu")


def test_merge_rejects_unprefixed_vertex():
    """If the subgraph carries a vertex not under <namespace>.*, merge refuses."""
    sub = GameGraph()
    sub.add_vertex("orphan")  # not prefixed with "plugin."
    main = GameGraph()
    with pytest.raises(GraphValidationError):
        main.merge(sub, namespace="plugin")


def test_merge_rejects_duplicate_vertex():
    sub = GameGraph()
    sub.add_vertex("plugin.entry")
    main = GameGraph()
    main.add_vertex("plugin.entry", owner="other")
    with pytest.raises(GraphValidationError):
        main.merge(sub, namespace="plugin")


def test_subgraph_of_filters_by_owner():
    g = GameGraph()
    g.add_vertex("main_menu", owner="main")
    g.add_vertex("plugin.entry", owner="plugin")
    g.add_vertex("plugin.exit", owner="plugin")
    g.add_edge("main_menu", "plugin.entry", action=_no_action)
    g.add_edge("plugin.entry", "plugin.exit", action=_no_action)

    sub = g.subgraph_of("plugin")
    ids = {v.id for v in sub.vertices()}
    assert ids == {"plugin.entry", "plugin.exit"}
    assert sub.has_edge("plugin.entry", "plugin.exit")
    # Cross-owner edge is dropped because its src is not in the filtered set.
    assert not sub.has_edge("main_menu", "plugin.entry")


def test_get_vertex_raises_on_unknown():
    g = GameGraph()
    with pytest.raises(UnknownVertex):
        g.get_vertex("missing")


def test_edge_cost_and_risky_fields_preserved():
    g = GameGraph()
    g.add_vertex("a")
    g.add_vertex("b")
    g.add_edge("a", "b", action=_no_action, cost=2.5, risky=True, tags=["ad"])
    e = g.get_edge("a", "b")
    assert e.cost == 2.5
    assert e.risky is True
    assert e.has_tag("ad")
