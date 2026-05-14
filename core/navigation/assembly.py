"""
`GraphAssembler` — merge main graph + enabled plugin subgraphs into one runnable graph.

Why a separate class instead of "just chain `.merge()` calls"
------------------------------------------------------------
Two reasons. First, plugins can be enabled or disabled per-account/session,
and we want the assembly step to know which plugins are participating so
dangling cross-namespace edges (e.g. `main_menu -> shop.entry` when `shop`
is off) become warnings, not crashes. Second, having a single object that
owns the assembled graph is the natural place to hang validation, logging,
and (later) reload semantics.

Usage
-----
::

    asm = GraphAssembler()
    asm.set_main(build_main_graph())
    asm.add_subgraph("daily_reward", build_daily_subgraph())
    asm.add_subgraph("shop",         build_shop_subgraph())
    graph = asm.assemble(enabled_plugins={"daily_reward"})  # shop dropped
"""

from __future__ import annotations

from typing import Dict, Optional, Set

from core.logging_config import get_logger
from core.navigation.graph import GameGraph

log = get_logger(__name__)


class GraphAssembler:
    """Stage + merge several `GameGraph` instances into one runnable graph."""

    def __init__(self) -> None:
        self._main: Optional[GameGraph] = None
        self._subgraphs: Dict[str, GameGraph] = {}

    # ------------------------------------------------------------------ #
    # Staging
    # ------------------------------------------------------------------ #
    def set_main(self, graph: GameGraph) -> "GraphAssembler":
        """Register the root graph. Calling twice replaces the prior one."""
        if not isinstance(graph, GameGraph):
            raise TypeError(f"main graph must be a GameGraph, got {type(graph).__name__}")
        self._main = graph
        return self

    def add_subgraph(self, namespace: str, graph: GameGraph) -> "GraphAssembler":
        """Register a plugin subgraph under `namespace`.

        Raises:
            ValueError: empty namespace or duplicate registration.
            TypeError: `graph` is not a `GameGraph`.
        """
        if not namespace:
            raise ValueError("namespace must be a non-empty string")
        if "." in namespace:
            raise ValueError(
                f"namespace must not contain '.', got {namespace!r}; "
                f"nested namespaces are not supported"
            )
        if not isinstance(graph, GameGraph):
            raise TypeError(
                f"subgraph must be a GameGraph, got {type(graph).__name__}"
            )
        if namespace in self._subgraphs:
            raise ValueError(f"subgraph {namespace!r} already registered")
        self._subgraphs[namespace] = graph
        return self

    @property
    def main(self) -> Optional[GameGraph]:
        return self._main

    @property
    def registered_namespaces(self) -> Set[str]:
        return set(self._subgraphs)

    # ------------------------------------------------------------------ #
    # Assembly
    # ------------------------------------------------------------------ #
    def assemble(
        self,
        enabled_plugins: Optional[Set[str]] = None,
        *,
        strict: bool = False,
    ) -> GameGraph:
        """Build the final graph.

        Steps:
            1. Start from the registered main graph (or an empty one if not set).
            2. Merge each registered subgraph whose namespace is in
               `enabled_plugins`. If `enabled_plugins` is None, merge *all*
               registered subgraphs.
            3. Run `validate()` on the result. Edges pointing at vertices
               that don't exist (because their plugin wasn't enabled) are
               dropped as dangling.

        Args:
            enabled_plugins: Whitelist of plugin namespaces to merge. Unknown
                names are silently ignored (with a warning) so callers can
                pass a static config without us crashing if a plugin was
                removed.
            strict: Forwarded to `GameGraph.validate`. Use in tests to catch
                dangling edges that were not intended.

        Returns:
            A fresh `GameGraph` containing only the enabled subgraphs.
        """
        if self._main is None:
            log.warning("GraphAssembler.assemble called with no main graph set")
            assembled = GameGraph()
        else:
            assembled = self._clone(self._main)

        if enabled_plugins is None:
            chosen = set(self._subgraphs)
        else:
            unknown = enabled_plugins - set(self._subgraphs)
            if unknown:
                log.warning(
                    "Unknown plugin namespace(s) in enabled set, ignored: %s",
                    sorted(unknown),
                )
            chosen = enabled_plugins & set(self._subgraphs)

        for ns in sorted(chosen):
            log.info("merging subgraph %r (%s)", ns, self._subgraphs[ns].describe())
            assembled.merge(self._subgraphs[ns], namespace=ns)

        disabled = set(self._subgraphs) - chosen
        if disabled:
            log.info("disabled plugin subgraph(s): %s", sorted(disabled))

        dangling = assembled.validate(strict=strict)
        if dangling:
            log.info(
                "assemble: dropped %d dangling edge(s) — disabled or missing target",
                len(dangling),
            )

        return assembled

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clone(graph: GameGraph) -> GameGraph:
        """Deep-ish copy of a `GameGraph`: keeps `Vertex`/`Edge` records (immutable)
        but produces a fresh underlying `nx.DiGraph` so `assemble()` doesn't
        mutate the source. Action callables are shared by reference — they
        are stateless, so this is fine and saves on duplication.
        """
        clone = GameGraph()
        for v in graph.vertices():
            clone.add_vertex(
                v.id,
                name=v.name,
                recognizer=v.recognizer,
                dwell_time=v.dwell_time,
                owner=v.owner,
            )
        for e in graph.edges():
            clone.add_edge(
                e.src,
                e.dst,
                action=e.action,
                cost=e.cost,
                risky=e.risky,
                tags=e.tags,
                cooldown=e.cooldown,
            )
        return clone
