"""DSL: subgraph() / root_graph() context, vertex(), edge(), external()."""

from __future__ import annotations

import pytest

from core.exceptions import GraphValidationError
from core.navigation import (
    GameGraph,
    edge,
    external,
    root_graph,
    subgraph,
    vertex,
)


def _no_action(_ctx):  # noqa: ANN001
    pass


def test_subgraph_prefixes_bare_vertex_ids():
    with subgraph("plugin") as g:
        vertex("entry")
        vertex("exit")
    assert g.has_vertex("plugin.entry")
    assert g.has_vertex("plugin.exit")
    assert g.vertex_owner("plugin.entry") == "plugin"


def test_subgraph_prefixes_bare_edge_endpoints():
    with subgraph("plugin") as g:
        vertex("a")
        vertex("b")
        edge("a", "b", action=_no_action)
    assert g.has_edge("plugin.a", "plugin.b")


def test_subgraph_keeps_dotted_edge_endpoints_verbatim():
    with subgraph("plugin") as g:
        vertex("a")
        edge("a", "other.entry", action=_no_action)
    assert g.has_edge("plugin.a", "other.entry")


def test_external_strips_namespace_for_root_refs():
    """`external("main_menu")` (no dot) must stay bare — used to reach root."""
    with subgraph("plugin") as g:
        vertex("a")
        edge("a", external("main_menu"), action=_no_action)
    assert g.has_edge("plugin.a", "main_menu")


def test_external_works_with_dotted_names_too():
    with subgraph("plugin") as g:
        vertex("a")
        edge("a", external("other.entry"), action=_no_action)
    assert g.has_edge("plugin.a", "other.entry")


def test_root_graph_no_prefix():
    with root_graph() as g:
        vertex("main_menu")
        vertex("profile")
        edge("main_menu", "profile", action=_no_action)
    assert g.has_vertex("main_menu")
    assert g.has_vertex("profile")
    assert g.has_edge("main_menu", "profile")
    # owner defaults to "main" in the root graph.
    assert g.vertex_owner("main_menu") == "main"


def test_calls_outside_context_fail():
    with pytest.raises(GraphValidationError):
        vertex("oops")
    with pytest.raises(GraphValidationError):
        edge("a", "b", action=_no_action)


def test_subgraph_requires_non_empty_namespace():
    with pytest.raises(ValueError):
        with subgraph(""):  # type: ignore[arg-type]
            pass


def test_external_requires_non_empty_name():
    with pytest.raises(ValueError):
        external("")


def test_nested_contexts_use_innermost():
    with subgraph("outer", graph=GameGraph()) as outer_g:
        vertex("a")  # registers outer.a
        with subgraph("inner", graph=GameGraph()) as inner_g:
            vertex("a")  # registers inner.a in inner_g
        # back in outer
        vertex("b")
    assert outer_g.has_vertex("outer.a")
    assert outer_g.has_vertex("outer.b")
    assert inner_g.has_vertex("inner.a")
    assert not inner_g.has_vertex("outer.a")
