"""Unit tests for `PluginRegistry`: register/discover/collect, failure isolation."""

from __future__ import annotations

import pytest

from core.exceptions import PluginDiscoveryFailed, PluginNotRegistered
from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin
from core.scheduler.registry import PluginRegistry


class _Plug(GameplayPlugin):
    name = "plug"

    @classmethod
    def build_subgraph(cls):
        g = GameGraph()
        g.add_vertex("plug.x", owner="plug")
        return g

    def setup(self, ctx):
        pass

    def run(self, ctx):
        pass

    def teardown(self, ctx):
        pass


class _OtherPlug(_Plug):
    name = "other"


class _BadName(_Plug):
    name = "has.dot"


class _BoomSubgraph(_Plug):
    name = "boom"

    @classmethod
    def build_subgraph(cls):
        raise RuntimeError("intentional")


def test_register_plain():
    reg = PluginRegistry()
    reg.register(_Plug)
    assert "plug" in reg
    assert reg.get("plug") is _Plug
    assert reg.list() == ["plug"]


def test_register_rejects_non_subclass():
    reg = PluginRegistry()
    with pytest.raises(PluginDiscoveryFailed):
        reg.register(object)  # type: ignore[arg-type]


def test_register_rejects_dot_in_name():
    reg = PluginRegistry()
    with pytest.raises(PluginDiscoveryFailed):
        reg.register(_BadName)


def test_register_collision_raises():
    class _Dup(_Plug):
        pass

    reg = PluginRegistry()
    reg.register(_Plug)
    with pytest.raises(PluginDiscoveryFailed):
        reg.register(_Dup)


def test_get_missing_raises():
    reg = PluginRegistry()
    with pytest.raises(PluginNotRegistered):
        reg.get("nope")


def test_collect_subgraphs_skips_failures():
    reg = PluginRegistry()
    reg.register(_Plug)
    reg.register(_BoomSubgraph)
    graphs = reg.collect_subgraphs()
    assert "plug" in graphs
    assert "boom" not in graphs
    assert any(f.module.endswith("build_subgraph") for f in reg.failed)


def test_collect_subgraphs_filters_by_only():
    reg = PluginRegistry()
    reg.register(_Plug)
    reg.register(_OtherPlug)
    graphs = reg.collect_subgraphs(only=["other"])
    assert "plug" not in graphs
    assert "other" in graphs


def test_collect_subgraphs_unknown_in_only_logs_warning():
    reg = PluginRegistry()
    reg.register(_Plug)
    graphs = reg.collect_subgraphs(only=["unknown"])
    assert graphs == {}


def test_discover_finds_demo_plugin():
    """End-to-end: scanning `plugins/` should find `_demo`."""
    reg = PluginRegistry()
    reg.discover()
    assert "_demo" in reg, f"discovered: {reg.list()}, failed: {reg.failed}"
