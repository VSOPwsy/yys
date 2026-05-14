"""
Render a `GameGraph` to PNG or an interactive window.

Usage::

    # Visualize the demo graph (root + _demo plugin):
    python dev_tools/graph_visualizer.py --demo --out demo_graph.png

    # Highlight a path:
    python dev_tools/graph_visualizer.py --demo --path main_menu _demo.step2

    # Visualize any importable build_*() callable:
    python dev_tools/graph_visualizer.py --build graphs._demo:build_main_graph \
        --out main_only.png

The output color-codes nodes by `Vertex.owner` and labels edges with cost.
Risky edges are drawn dashed.

Per CLAUDE.md S3: this file lives in `dev_tools/` and **must not** be imported
by `core/`, `plugins/`, or `main.py`.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib

# Allow saving without an interactive backend (e.g. in CI).
import matplotlib.pyplot as plt
import networkx as nx

# Try to find a CJK-capable font on this machine so vertex labels with
# Chinese characters render as glyphs rather than tofu boxes. Falls back
# silently if none are installed.
for _cjk_font in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "PingFang SC"):
    if any(_cjk_font.lower() == f.name.lower()
           for f in matplotlib.font_manager.fontManager.ttflist):
        matplotlib.rcParams["font.sans-serif"] = [_cjk_font]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break

from core.navigation import GameGraph, GraphAssembler, PathFinder  # noqa: E402


def _load_callable(spec: str):
    """`mod.path:callable` -> the callable. Raises clear errors on typos."""
    if ":" not in spec:
        raise ValueError(f"--build expects 'module:callable', got {spec!r}")
    mod_name, fn_name = spec.split(":", 1)
    mod = importlib.import_module(mod_name)
    if not hasattr(mod, fn_name):
        raise AttributeError(f"{mod_name!r} has no attribute {fn_name!r}")
    return getattr(mod, fn_name)


def _build_demo_graph() -> GameGraph:
    """Assemble the Phase 2 demo graph (root + _demo plugin)."""
    from graphs._demo import build_main_graph
    from plugins._demo.graph import build_subgraph

    asm = GraphAssembler()
    asm.set_main(build_main_graph())
    asm.add_subgraph("_demo", build_subgraph())
    return asm.assemble()


def _owner_color(owner: Optional[str], palette: dict) -> str:
    if owner not in palette:
        # Cycle through a stable palette without depending on order of arrival.
        defaults = ["#9ecae1", "#a1d99b", "#fdae6b", "#bcbddc", "#fa9fb5"]
        palette[owner] = defaults[len(palette) % len(defaults)]
    return palette[owner]


def visualize(
    graph: GameGraph,
    *,
    out: Optional[Path] = None,
    show: bool = False,
    highlight_path: Optional[List[Tuple[str, str]]] = None,
    figsize: Tuple[int, int] = (12, 8),
) -> None:
    """Render `graph`. Set either `out` to save a PNG or `show=True` to open
    an interactive window."""
    if not show and out is None:
        # Default to saving next to the project root.
        out = PROJECT_ROOT / "graph.png"

    if not show:
        matplotlib.use("Agg")

    g = graph.nx
    layout = nx.spring_layout(g, seed=42, k=0.9)

    palette: dict = {}
    node_colors = [
        _owner_color(graph.get_vertex(n).owner, palette)
        if "vertex" in g.nodes[n]
        else "#cccccc"
        for n in g.nodes
    ]
    node_labels = {
        n: (graph.get_vertex(n).display_label() if "vertex" in g.nodes[n] else f"{n}?")
        for n in g.nodes
    }

    fig, ax = plt.subplots(figsize=figsize)
    nx.draw_networkx_nodes(
        g, layout, node_color=node_colors, node_size=1800, ax=ax
    )
    nx.draw_networkx_labels(g, layout, labels=node_labels, font_size=9, ax=ax)

    # Split edges into normal / risky / highlighted so each can use its own style.
    highlight_set = set(highlight_path or [])
    risky_edges = [
        (u, v) for u, v, d in g.edges(data=True) if d["edge"].risky and (u, v) not in highlight_set
    ]
    normal_edges = [
        (u, v) for u, v, d in g.edges(data=True)
        if not d["edge"].risky and (u, v) not in highlight_set
    ]
    if normal_edges:
        nx.draw_networkx_edges(g, layout, edgelist=normal_edges,
                               edge_color="#555", arrows=True, ax=ax)
    if risky_edges:
        nx.draw_networkx_edges(g, layout, edgelist=risky_edges,
                               edge_color="#d62728", style="dashed",
                               arrows=True, ax=ax)
    if highlight_set:
        nx.draw_networkx_edges(g, layout, edgelist=list(highlight_set),
                               edge_color="#1f77b4", width=2.5, arrows=True, ax=ax)

    edge_labels = {
        (u, v): f"{d['edge'].cost:.1f}"
        + ("!" if d["edge"].risky else "")
        for u, v, d in g.edges(data=True)
    }
    nx.draw_networkx_edge_labels(g, layout, edge_labels=edge_labels, font_size=7, ax=ax)

    # Legend: one swatch per owner.
    handles = [
        plt.Line2D([0], [0], marker="o", color="w", label=str(owner),
                   markerfacecolor=color, markersize=10)
        for owner, color in palette.items()
    ]
    if handles:
        ax.legend(handles=handles, title="owner", loc="best", fontsize=8)

    ax.set_title(repr(graph))
    ax.set_axis_off()
    fig.tight_layout()

    if out is not None:
        fig.savefig(str(out), dpi=150)
        print(f"saved {out}")
    if show:
        plt.show()
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true",
                       help="Render the assembled Phase 2 demo graph.")
    group.add_argument("--build",
                       help="module:callable that returns a GameGraph.")
    parser.add_argument("--out", type=Path, default=None,
                        help="PNG output path. Default: project/graph.png.")
    parser.add_argument("--show", action="store_true",
                        help="Open an interactive matplotlib window.")
    parser.add_argument("--path", nargs=2, metavar=("FROM", "TO"),
                        help="Highlight the shortest path from FROM to TO.")
    args = parser.parse_args()

    if args.demo:
        graph = _build_demo_graph()
    else:
        graph = _load_callable(args.build)()
        if not isinstance(graph, GameGraph):
            raise TypeError(
                f"--build callable must return GameGraph, got {type(graph).__name__}"
            )

    highlight = None
    if args.path:
        edges = PathFinder(graph).shortest_path(args.path[0], args.path[1])
        highlight = [(e.src, e.dst) for e in edges]
        print("path:", " -> ".join([args.path[0], *(e.dst for e in edges)]))

    visualize(graph, out=args.out, show=args.show, highlight_path=highlight)


if __name__ == "__main__":
    main()
