"""
`PathFinder` — search routes through an assembled `GameGraph`.

Three search modes:

* `shortest_path(src, dst)` — `nx.shortest_path` with `cost` as weight.
  Constraint filters (`avoid_risky`, `avoid_tags`) work by re-weighting the
  banned edges to ``+inf`` so a banned route is only chosen when there is no
  alternative.

* `random_path(src, dst)` — explores `nx.all_simple_paths` up to a length
  budget derived from the shortest path, then picks one at random. This is
  the "humanize movement" hook: with multiple viable routes, repeated
  invocations should not always pick the same one.

* `all_paths(src, dst, max_length=K)` — returns every simple path with at
  most K vertices. Cheap when the graph is small; the user is responsible
  for capping `max_length` on dense graphs.

Important: `PathFinder` is unaware of namespaces. Inputs and outputs use
fully-qualified ids (e.g. ``daily_reward.entry``), which is what the
assembled graph stores.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, List, Optional, Set

import networkx as nx

from core.exceptions import NoPathFound, UnknownVertex
from core.logging_config import get_logger
from core.navigation.graph import Edge, GameGraph

log = get_logger(__name__)


class PathFinder:
    """Pathfinding wrapper over a `GameGraph`."""

    def __init__(self, graph: GameGraph) -> None:
        self._graph = graph

    @property
    def graph(self) -> GameGraph:
        return self._graph

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def shortest_path(
        self,
        start: str,
        end: str,
        *,
        avoid_risky: bool = False,
        avoid_tags: Optional[Iterable[str]] = None,
    ) -> List[Edge]:
        """Minimum-cost path as a list of `Edge` records.

        Args:
            start, end: Fully-qualified vertex ids.
            avoid_risky: Skip edges marked `risky=True`. Falls back to a risky
                edge only when no risk-free path exists.
            avoid_tags: Skip edges whose `tags` intersect with this set.

        Returns:
            Ordered list of edges to traverse. Empty list iff `start == end`.

        Raises:
            UnknownVertex: `start` or `end` not in the graph.
            NoPathFound: No reachable route (also when every route is banned
                by filters).
        """
        self._require_vertex(start)
        self._require_vertex(end)
        if start == end:
            return []

        banned = self._banned_set(avoid_risky, avoid_tags)
        weight_fn = self._weight_fn(banned)

        try:
            vertex_path = nx.shortest_path(
                self._graph.nx, start, end, weight=weight_fn
            )
        except nx.NetworkXNoPath as e:
            raise NoPathFound(f"No path from {start!r} to {end!r}") from e

        edges = self._edges_along(vertex_path)
        # If every alternative was banned, we may have picked one. Surface
        # that to the caller so they can decide what to do.
        total = sum(weight_fn(e.src, e.dst, {}) for e in edges)
        if total == math.inf:
            raise NoPathFound(
                f"No path from {start!r} to {end!r} satisfying "
                f"avoid_risky={avoid_risky} avoid_tags={sorted(avoid_tags or [])!r}"
            )
        return edges

    def random_path(
        self,
        start: str,
        end: str,
        *,
        avoid_risky: bool = False,
        avoid_tags: Optional[Iterable[str]] = None,
        max_paths: int = 10,
        max_length_factor: float = 1.5,
        rng: Optional[random.Random] = None,
    ) -> List[Edge]:
        """Random viable path from `start` to `end`.

        Strategy:
            1. Compute the shortest-path length (in vertices). Call it L.
            2. Enumerate up to `max_paths` simple paths with at most
               ``ceil(L * max_length_factor)`` vertices, filtering out any
               that contain a banned edge.
            3. Pick one uniformly at random.

        This is intentionally bounded: enumerating all simple paths on a real
        UI graph is fine, but we cap it to keep runtime predictable.

        Args:
            start, end: Fully-qualified vertex ids.
            avoid_risky / avoid_tags: Same semantics as `shortest_path`.
            max_paths: Cap on how many candidates we collect before sampling.
            max_length_factor: Multiplier over the shortest path length to
                bound enumeration. 1.0 = only optimal-length paths; 1.5
                allows mild detours; large values approach "all simple paths".
            rng: Injection point for tests. Defaults to `random` module.

        Returns:
            Edge list, never empty (unless start == end).

        Raises:
            UnknownVertex / NoPathFound: Same as `shortest_path`.
            ValueError: invalid `max_paths` or `max_length_factor`.
        """
        if max_paths < 1:
            raise ValueError(f"max_paths must be >= 1, got {max_paths}")
        if max_length_factor < 1.0:
            raise ValueError(
                f"max_length_factor must be >= 1.0, got {max_length_factor}"
            )

        # Shortest path also validates start/end exist and gives us the budget.
        shortest = self.shortest_path(
            start, end, avoid_risky=avoid_risky, avoid_tags=avoid_tags
        )
        if not shortest:
            return []

        rng = rng or random
        banned = self._banned_set(avoid_risky, avoid_tags)
        # max_length is measured in vertices (== edges + 1).
        max_vertices = max(2, math.ceil((len(shortest) + 1) * max_length_factor))

        candidates: List[List[Edge]] = []
        for vpath in nx.all_simple_paths(
            self._graph.nx, start, end, cutoff=max_vertices - 1
        ):
            edges = self._edges_along(vpath)
            if any((e.src, e.dst) in banned for e in edges):
                continue
            candidates.append(edges)
            if len(candidates) >= max_paths:
                break

        if not candidates:
            # The constraint filters wiped out the shortest path AND
            # everything in budget. Fall back to that (we know it exists).
            return shortest

        return rng.choice(candidates)

    def all_paths(
        self,
        start: str,
        end: str,
        *,
        max_length: Optional[int] = None,
    ) -> List[List[Edge]]:
        """Return every simple path from `start` to `end`.

        Args:
            max_length: Cap on path length in *vertices* (== edges + 1).
                Defaults to None = no cap; use carefully on dense graphs.

        Returns:
            List of paths; each path is a list of `Edge` in traversal order.

        Raises:
            UnknownVertex: `start` or `end` not in the graph.
        """
        self._require_vertex(start)
        self._require_vertex(end)
        if start == end:
            return [[]]

        cutoff = None if max_length is None else max(1, max_length - 1)
        result: List[List[Edge]] = []
        for vpath in nx.all_simple_paths(
            self._graph.nx, start, end, cutoff=cutoff
        ):
            result.append(self._edges_along(vpath))
        return result

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _require_vertex(self, vid: str) -> None:
        if not self._graph.has_vertex(vid):
            raise UnknownVertex(f"Vertex {vid!r} not in graph")

    def _banned_set(
        self,
        avoid_risky: bool,
        avoid_tags: Optional[Iterable[str]],
    ) -> Set[tuple]:
        """Return the set of (src, dst) pairs to ban based on filters."""
        tag_filter: Set[str] = set(avoid_tags or ())
        banned: Set[tuple] = set()
        if not avoid_risky and not tag_filter:
            return banned
        for e in self._graph.edges():
            if avoid_risky and e.risky:
                banned.add((e.src, e.dst))
                continue
            if tag_filter and tag_filter.intersection(e.tags):
                banned.add((e.src, e.dst))
        return banned

    def _weight_fn(self, banned: Set[tuple]):
        """Build the weight function networkx will call per edge.

        Banned edges return ``+inf`` so shortest_path routes around them
        whenever any alternative exists. (networkx accepts inf; nodes are
        only chosen with a banned edge if there is literally no other way.)
        """
        g = self._graph

        def weight(src, dst, _data):
            if (src, dst) in banned:
                return math.inf
            return g.get_edge(src, dst).cost

        return weight

    def _edges_along(self, vertex_path: List[str]) -> List[Edge]:
        """Materialize a vertex-id path into the actual `Edge` records."""
        return [
            self._graph.get_edge(a, b)
            for a, b in zip(vertex_path, vertex_path[1:])
        ]
