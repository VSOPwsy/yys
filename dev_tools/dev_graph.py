"""
Helper callables that assemble the **full** game graph for dev_tools.

Problem this exists to solve
----------------------------
``graphs.main:build_main_graph`` only constructs the *root* namespace
graph. In production, ``main.py`` then:

    1. Runs ``PluginRegistry.discover()`` to find all plugins.
    2. Calls ``GraphAssembler`` to merge each plugin's subgraph into
       the root.
    3. Drops dangling cross-namespace edges (e.g. ``tingyuan ->
       shishenlu.home``) when a plugin is disabled in config.

dev_tools scripts (``nav_smoke.py``, ``screen_inspector.py``,
``graph_visualizer.py``) take ``--graph mod:fn`` and call ``fn()``. If
they point at ``graphs.main:build_main_graph`` they only see the root
graph — plugin vertices are missing and cross-namespace edges look like
typos. This module provides a callable that returns the assembled
graph instead, so ``--graph dev_tools.dev_graph:build_full_graph``
gives the dev tool the same view the production scheduler builds.

Usage
-----
::

    python dev_tools/nav_smoke.py --mumu "..." \\
        --graph dev_tools.dev_graph:build_full_graph \\
        --target shishenlu.home
"""

from __future__ import annotations

from core.navigation.assembly import GraphAssembler
from core.navigation.graph import GameGraph
from core.scheduler.registry import PluginRegistry
from graphs.main import build_main_graph


def build_full_graph() -> GameGraph:
    """Build the production root graph + all discovered plugin subgraphs.

    Unlike production (which only merges plugins enabled in
    ``config.yaml``), this merges **every** plugin discovered under
    ``plugins/``. Convenient for dev tools — you can navigate to any
    plugin's vertices regardless of whether the plugin is on for
    today's run.

    Returns:
        An assembled `GameGraph`. Dangling edges (if any) are dropped
        with a warning, same as production.
    """
    registry = PluginRegistry()
    registry.discover()
    asm = GraphAssembler()
    asm.set_main(build_main_graph())
    subs = registry.collect_subgraphs()
    for namespace, sg in subs.items():
        asm.add_subgraph(namespace, sg)
    return asm.assemble(enabled_plugins=set(subs))
