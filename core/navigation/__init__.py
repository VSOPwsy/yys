"""
Phase 2 navigation layer.

Subpackage layout:
  * `graph`      — `GameGraph`, the core `networkx.DiGraph` wrapper with
                   `Vertex` / `Edge` records and namespace-aware `merge()`.
  * `builder`    — DSL: `subgraph()` context manager, `vertex()` / `edge()`
                   recorders, `external()` annotation, and action factories
                   (`click_button`, `wait`, `press_back`, `swipe_dir`,
                   `swipe_to`, `click_at`, `compose`, `conditional`).
  * `assembly`   — `GraphAssembler` merges main + selected subgraphs and runs
                   `validate()` so dangling edges become warnings, not crashes.
  * `pathfinder` — `PathFinder`: shortest/random/all path search over the
                   assembled graph with `avoid_risky` / `avoid_tags`.
  * `recognizer` — `ScreenRecognizer`: identify "which vertex are we on?" by
                   asking each vertex's recognizer in turn.
  * `navigator`  — `Navigator`: ties it all together — `goto(vertex_id)`.

Public re-exports below keep `from core.navigation import GameGraph, ...`
cheap for callers (the demo + tests rely on this).
"""

from core.navigation.graph import Edge, GameGraph, Vertex
from core.navigation.builder import (
    NavigationContext,
    SubgraphBuilder,
    click_at,
    click_button,
    compose,
    conditional,
    edge,
    external,
    press_back,
    root_graph,
    subgraph,
    swipe_dir,
    swipe_to,
    vertex,
    wait,
)
from core.navigation.assembly import GraphAssembler
from core.navigation.pathfinder import PathFinder
from core.navigation.recognizer import ScreenRecognizer
from core.navigation.navigator import Navigator

__all__ = [
    "Edge",
    "GameGraph",
    "GraphAssembler",
    "NavigationContext",
    "Navigator",
    "PathFinder",
    "ScreenRecognizer",
    "SubgraphBuilder",
    "Vertex",
    "click_at",
    "click_button",
    "compose",
    "conditional",
    "edge",
    "external",
    "press_back",
    "root_graph",
    "subgraph",
    "swipe_dir",
    "swipe_to",
    "vertex",
    "wait",
]
