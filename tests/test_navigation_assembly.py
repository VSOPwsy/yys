"""GraphAssembler: enable/disable plugins, drop dangling edges to disabled targets."""

from __future__ import annotations

import pytest

from core.exceptions import GraphValidationError
from core.navigation import (
    GameGraph,
    GraphAssembler,
    edge,
    external,
    root_graph,
    subgraph,
    vertex,
)


def _no_action(_ctx):  # noqa: ANN001
    pass


def _build_main_graph() -> GameGraph:
    with root_graph() as g:
        vertex("main_menu")
        # Two plugin entry points; either may or may not be enabled.
        edge("main_menu", "plugin_a.entry", action=_no_action)
        edge("main_menu", "plugin_b.entry", action=_no_action)
    return g


def _build_plugin_a() -> GameGraph:
    with subgraph("plugin_a") as g:
        vertex("entry")
        vertex("exit")
        edge("entry", "exit", action=_no_action)
        edge("exit", external("main_menu"), action=_no_action)
    return g


def _build_plugin_b() -> GameGraph:
    with subgraph("plugin_b") as g:
        vertex("entry")
    return g


def test_assemble_with_all_plugins_enabled():
    asm = GraphAssembler()
    asm.set_main(_build_main_graph())
    asm.add_subgraph("plugin_a", _build_plugin_a())
    asm.add_subgraph("plugin_b", _build_plugin_b())
    g = asm.assemble(enabled_plugins={"plugin_a", "plugin_b"})
    assert g.has_vertex("main_menu")
    assert g.has_vertex("plugin_a.entry")
    assert g.has_vertex("plugin_b.entry")
    assert g.has_edge("main_menu", "plugin_a.entry")
    assert g.has_edge("main_menu", "plugin_b.entry")


def test_assemble_with_one_plugin_disabled_drops_dangling_edge(caplog):
    asm = GraphAssembler()
    asm.set_main(_build_main_graph())
    asm.add_subgraph("plugin_a", _build_plugin_a())
    asm.add_subgraph("plugin_b", _build_plugin_b())
    with caplog.at_level("WARNING"):
        g = asm.assemble(enabled_plugins={"plugin_a"})  # b disabled
    assert g.has_vertex("plugin_a.entry")
    assert not g.has_vertex("plugin_b.entry")
    # The main->plugin_b.entry edge should be dropped, not crash.
    assert not g.has_edge("main_menu", "plugin_b.entry")
    # Plugin A's cross-namespace return edge to main_menu survives.
    assert g.has_edge("plugin_a.exit", "main_menu")


def test_assemble_with_no_filter_includes_all():
    asm = GraphAssembler()
    asm.set_main(_build_main_graph())
    asm.add_subgraph("plugin_a", _build_plugin_a())
    g = asm.assemble()  # enabled_plugins=None means "all"
    assert g.has_vertex("plugin_a.entry")


def test_assemble_warns_on_unknown_plugin_in_enabled_set(caplog):
    asm = GraphAssembler()
    asm.set_main(_build_main_graph())
    with caplog.at_level("WARNING"):
        asm.assemble(enabled_plugins={"never_registered"})
    assert any("Unknown plugin" in r.message for r in caplog.records)


def test_duplicate_subgraph_registration_rejected():
    asm = GraphAssembler()
    asm.add_subgraph("plugin_a", _build_plugin_a())
    with pytest.raises(ValueError):
        asm.add_subgraph("plugin_a", _build_plugin_a())


def test_assemble_strict_propagates_validation_error():
    asm = GraphAssembler()
    asm.set_main(_build_main_graph())
    # Don't register either plugin: the main graph's edges to them dangle.
    with pytest.raises(GraphValidationError):
        asm.assemble(enabled_plugins=set(), strict=True)
