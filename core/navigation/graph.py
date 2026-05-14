"""
`GameGraph` — handwritten directed graph of game screens.

Vertices are *stable UI states* (e.g. "main_menu", "daily_reward.entry"). Edges
are operations that take us from one vertex to another (a click, a swipe, a
wait). The graph is the source of truth for "how the UI is wired"; pathfinding
and execution layers consume it without modifying it.

Design choices worth knowing
----------------------------
* **Namespace-aware merge.** Plugins register their internal vertices under
  their own namespace (e.g. `daily_reward.entry`). `GameGraph.merge(other,
  namespace="daily_reward")` rewrites bare ids in `other` to that namespace
  and leaves already-qualified references untouched, so plugins can declare
  cross-boundary edges (`reward_list -> main.main_menu`) without the parent
  graph having to know about them.

* **Dangling edges are warnings, not errors.** A subgraph might point at a
  vertex owned by a plugin that wasn't enabled this session. `validate()`
  collects those into `dangling_edges` and (by default) drops them with a
  log line; `strict=True` flips that to a hard `GraphValidationError`. This
  is what lets `GraphAssembler` ship a runnable graph even when half the
  plugins are off.

* **`networkx.DiGraph` underneath.** We don't subclass — composition lets us
  add invariants (unique vertex, owner stamping) without re-implementing the
  pathfinding/iteration primitives networkx already does well.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

import networkx as nx

from core.exceptions import GraphValidationError, UnknownVertex
from core.logging_config import get_logger

log = get_logger(__name__)

# A vertex recognizer takes a BGR screenshot and returns True iff "we are
# currently on this screen". Concrete forms (Button, str, callable) are
# resolved by `ScreenRecognizer`; the graph just stores whatever was passed.
Recognizer = Any

# An edge action takes a navigation context object and executes the
# transition (clicking, waiting, etc.). The context exposes the backend +
# whatever else higher layers want to provide; we don't pin its type here so
# Phase 3's PluginContext can slot in without breaking us.
Action = Callable[[Any], None]


@dataclass(frozen=True)
class Vertex:
    """One stable UI state.

    Attributes:
        id: Fully-qualified id inside the assembled graph (e.g.
            "daily_reward.entry"). Inside a plugin's subgraph it starts as a
            bare name; `merge()` prefixes it.
        name: Human-readable label for logs / tools. Defaults to `id`.
        recognizer: How to detect "are we on this screen right now?" Accepts
            anything `ScreenRecognizer` knows how to coerce (Button, str, or
            callable). Required, but the graph never invokes it directly.
        dwell_time: Default settle delay (milliseconds) after arriving here.
            Lets animations / loading spinners finish before we screenshot
            again. Navigator honors it; PathFinder ignores it.
        owner: Which namespace this vertex belongs to. "main" for the root
            graph, "<plugin>" for a plugin subgraph. Set by `merge()`; the
            handwritten DSL doesn't usually need to touch it.
    """

    id: str
    name: str
    recognizer: Recognizer
    dwell_time: int = 500
    owner: Optional[str] = None

    def display_label(self) -> str:
        """Pretty label for tools / logs: ``name (id)`` when they differ."""
        return self.name if self.name == self.id else f"{self.name} ({self.id})"


@dataclass(frozen=True)
class Edge:
    """One operation that transitions from `src` to `dst`.

    Attributes:
        src: Fully-qualified id of the source vertex.
        dst: Fully-qualified id of the destination vertex.
        action: Callable that performs the transition. Receives a navigation
            context (see module docstring). Must NOT raise on the happy path.
        cost: Predicted seconds-to-complete. Used as the edge weight by
            `PathFinder`. A reasonable proxy for "how much real time will
            this path eat".
        risky: Marks operations that may spend resources / be irreversible
            (a "purchase", "consume ticket", "skip cutscene with reward"
            choice). `PathFinder(avoid_risky=True)` routes around these.
        tags: Free-form labels. PathFinder's `avoid_tags=` filter takes a
            set of tags and skips any edge that carries them. Useful for
            "advertise"-style edges or experimental routes.
        cooldown: Minimum seconds between consecutive uses of this exact
            edge. Phase 2 stores the value; future executors will enforce
            it (a "don't double-click the daily chest" guard).
    """

    src: str
    dst: str
    action: Action
    cost: float = 1.0
    risky: bool = False
    tags: Tuple[str, ...] = field(default_factory=tuple)
    cooldown: float = 0.0

    def has_tag(self, tag: str) -> bool:
        """True iff `tag` appears in `tags`. Sugar for filter expressions."""
        return tag in self.tags


class GameGraph:
    """Namespace-aware wrapper around `networkx.DiGraph`.

    Methods marked **public** are the supported API; touching `_g` directly is
    fine inside `core.navigation` but treated as private elsewhere.
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()
        # Dangling edges accumulated by the last `validate()` call. Useful
        # for debugging and for `GraphAssembler` to log a clean summary.
        self.dangling_edges: List[Edge] = []

    # ------------------------------------------------------------------ #
    # Vertex / edge mutation
    # ------------------------------------------------------------------ #
    def add_vertex(
        self,
        id: str,
        *,
        name: Optional[str] = None,
        recognizer: Recognizer = None,
        dwell_time: int = 500,
        owner: Optional[str] = None,
    ) -> Vertex:
        """Register a new vertex. Duplicate ids raise `GraphValidationError`.

        Returns the stored `Vertex` so callers can chain.
        """
        if not id:
            raise ValueError("Vertex id must be a non-empty string")
        existing = self._g.nodes.get(id)
        if existing is not None and "vertex" in existing:
            # Real, registered duplicate. Refuse — each id has one owner.
            raise GraphValidationError(
                f"Vertex {id!r} already defined (owner={self.vertex_owner(id)!r}); "
                f"each vertex must be owned by exactly one namespace"
            )
        vertex = Vertex(
            id=id,
            name=name or id,
            recognizer=recognizer,
            dwell_time=dwell_time,
            owner=owner,
        )
        # `add_node` keeps existing edges if the node already exists as a
        # ghost (auto-created by `add_edge`). That's exactly what we want
        # when a cross-namespace edge was registered before its target.
        self._g.add_node(id, vertex=vertex)
        return vertex

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        *,
        action: Action,
        cost: float = 1.0,
        risky: bool = False,
        tags: Optional[Iterable[str]] = None,
        cooldown: float = 0.0,
    ) -> Edge:
        """Register a new edge. Both vertices may be undefined at this point.

        We intentionally do NOT require both endpoints to exist yet —
        cross-namespace edges from a plugin subgraph reference vertices owned
        by other namespaces, which only show up after `merge()`. The dangling
        check happens in `validate()`.
        """
        if cost < 0:
            raise ValueError(f"Edge cost must be >= 0, got {cost}")
        if cooldown < 0:
            raise ValueError(f"Edge cooldown must be >= 0, got {cooldown}")
        edge = Edge(
            src=from_id,
            dst=to_id,
            action=action,
            cost=cost,
            risky=risky,
            tags=tuple(tags or ()),
            cooldown=cooldown,
        )
        # MultiDiGraph would let us model "two ways to get there", but it
        # complicates pathfinding; for now we keep one canonical edge per pair.
        if self._g.has_edge(from_id, to_id):
            raise GraphValidationError(
                f"Edge {from_id!r} -> {to_id!r} already defined; merge or split it"
            )
        self._g.add_edge(from_id, to_id, edge=edge)
        return edge

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    def get_vertex(self, id: str) -> Vertex:
        """Return the stored `Vertex` or raise `UnknownVertex`."""
        if id not in self._g:
            raise UnknownVertex(f"Vertex {id!r} not in graph")
        return self._g.nodes[id]["vertex"]

    def has_vertex(self, id: str) -> bool:
        """True iff `id` is registered."""
        return id in self._g

    def vertex_owner(self, id: str) -> Optional[str]:
        """Convenience: owner of the registered vertex, or None if missing/ghost."""
        if id not in self._g:
            return None
        data = self._g.nodes[id]
        if "vertex" not in data:
            return None
        return data["vertex"].owner

    def get_edge(self, from_id: str, to_id: str) -> Edge:
        """Return the stored `Edge` or raise `UnknownVertex` / KeyError."""
        if not self._g.has_edge(from_id, to_id):
            raise UnknownVertex(f"No edge {from_id!r} -> {to_id!r}")
        return self._g[from_id][to_id]["edge"]

    def has_edge(self, from_id: str, to_id: str) -> bool:
        return self._g.has_edge(from_id, to_id)

    def vertices(self) -> Iterator[Vertex]:
        """Iterate all *registered* `Vertex` records.

        Skips ghost nodes that networkx auto-created when an `add_edge` ran
        before the other end's `add_vertex` (typical for cross-namespace
        edges; `validate()` will drop them later).
        """
        for _, data in self._g.nodes(data=True):
            if "vertex" in data:
                yield data["vertex"]

    def edges(self) -> Iterator[Edge]:
        """Iterate all stored `Edge` records."""
        for _, _, data in self._g.edges(data=True):
            yield data["edge"]

    def vertex_ids(self) -> List[str]:
        """Ids of registered vertices (excludes ghost endpoints from edges)."""
        return [n for n, d in self._g.nodes(data=True) if "vertex" in d]

    @property
    def nx(self) -> nx.DiGraph:
        """Direct access to the underlying `networkx.DiGraph`.

        Exposed so `PathFinder` and visualization tools can call networkx
        primitives without the wrapper getting in the way. Mutating the
        returned graph bypasses our invariants — only do so inside
        `core.navigation`.
        """
        return self._g

    def __len__(self) -> int:
        return len(self._g)

    def __contains__(self, vertex_id: str) -> bool:
        return vertex_id in self._g

    # ------------------------------------------------------------------ #
    # Namespace operations
    # ------------------------------------------------------------------ #
    def merge(self, other: "GameGraph", namespace: str) -> "GameGraph":
        """Merge `other` into self, stamping its vertices with `owner=namespace`.

        Pre-conditions on `other` (enforced by the DSL — see
        `core.navigation.builder`):
            * every registered vertex id is fully qualified, i.e. it starts
              with ``"<namespace>."`` (or is wrapped via `external()`).
            * cross-namespace edge endpoints are stored verbatim (dotted ids
              for explicit cross-namespace, or `external()` results for the
              root namespace, which has no prefix).

        This method therefore does *not* re-prefix anything; it copies the
        registered vertices (stamping owner) and the edges (verbatim). The
        merge namespace parameter is still required because:
            (a) we validate that vertex ids actually carry the prefix
                (catches "wrong namespace argument" typos),
            (b) ``Vertex.owner`` is set to it.

        Forward references in `other` (ghost nodes that networkx auto-created
        for cross-namespace edges) are intentionally NOT brought across as
        registered vertices — they will be resolved by future merges or
        dropped by `validate()`.

        Returns `self` for chaining.

        Raises:
            ValueError: empty namespace.
            GraphValidationError: a vertex id collides with one already in
                `self`, or an `other` vertex id does not start with
                `<namespace>.`.
        """
        if not namespace:
            raise ValueError("namespace must be a non-empty string")
        prefix = f"{namespace}."

        # Pre-flight: every registered vertex in `other` must already be
        # under `namespace.*`. Cross-namespace references appear only as
        # ghost endpoints of edges — those are absorbed naturally below
        # (we just copy them as-is and let validate() prune any leftovers).
        for vid, data in other._g.nodes(data=True):
            if "vertex" not in data:
                continue
            if not vid.startswith(prefix):
                raise GraphValidationError(
                    f"merge({namespace!r}): vertex {vid!r} is not under that "
                    f"namespace; rebuild the subgraph with a matching "
                    f"`subgraph(\"{namespace}\")` block"
                )
            if vid in self._g and "vertex" in self._g.nodes[vid]:
                raise GraphValidationError(
                    f"merge({namespace!r}): vertex {vid!r} already owned by "
                    f"{self.vertex_owner(vid)!r}; cannot merge"
                )

        # Vertices: copy, stamp owner. Recognizers/dwell time travel intact.
        for vid, data in other._g.nodes(data=True):
            if "vertex" not in data:
                continue
            v: Vertex = data["vertex"]
            self.add_vertex(
                vid,
                name=v.name,
                recognizer=v.recognizer,
                dwell_time=v.dwell_time,
                owner=namespace,
            )

        # Edges: verbatim. Endpoints may not exist in self yet — `validate()`
        # is where we deal with the leftovers.
        for src, dst, data in other._g.edges(data=True):
            e: Edge = data["edge"]
            self.add_edge(
                src,
                dst,
                action=e.action,
                cost=e.cost,
                risky=e.risky,
                tags=e.tags,
                cooldown=e.cooldown,
            )

        return self

    def subgraph_of(self, namespace: str) -> "GameGraph":
        """Return a new `GameGraph` containing only vertices owned by `namespace`.

        Edges are copied iff *both* endpoints survive the filter. Intended for
        debugging / visualization — not a hot path.
        """
        sub = GameGraph()
        kept_ids: Set[str] = set()
        for v in self.vertices():
            if v.owner == namespace:
                sub.add_vertex(
                    v.id,
                    name=v.name,
                    recognizer=v.recognizer,
                    dwell_time=v.dwell_time,
                    owner=v.owner,
                )
                kept_ids.add(v.id)
        for e in self.edges():
            if e.src in kept_ids and e.dst in kept_ids:
                sub.add_edge(
                    e.src,
                    e.dst,
                    action=e.action,
                    cost=e.cost,
                    risky=e.risky,
                    tags=e.tags,
                    cooldown=e.cooldown,
                )
        return sub

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate(self, *, strict: bool = False) -> List[Edge]:
        """Sweep for dangling edges.

        An edge is dangling iff `src` or `dst` is not a registered vertex.
        That happens when (a) a plugin's cross-namespace edge points at a
        plugin that isn't enabled in this session, or (b) the developer
        typo'd a reference.

        Behavior:
            * Dangling edges are removed from the underlying graph and saved
              into `self.dangling_edges` for inspection.
            * `strict=False` (default): log a warning, return the list.
            * `strict=True`: raise `GraphValidationError` with the list.

        Returns the list of dangling edges that were dropped.
        """
        # An endpoint is "registered" iff our `add_vertex` ran for it (which
        # stamps `node["vertex"]`). Bare nodes that networkx auto-created via
        # `add_edge` are the dangling marker.
        dangling: List[Edge] = []
        to_remove: List[Tuple[str, str]] = []
        for src, dst, data in self._g.edges(data=True):
            src_ok = "vertex" in self._g.nodes[src]
            dst_ok = "vertex" in self._g.nodes[dst]
            if not (src_ok and dst_ok):
                dangling.append(data["edge"])
                to_remove.append((src, dst))

        for src, dst in to_remove:
            self._g.remove_edge(src, dst)
            # Drop ghost nodes that networkx auto-created for the missing endpoint.
            for endpoint in (src, dst):
                if (
                    endpoint in self._g.nodes
                    and "vertex" not in self._g.nodes[endpoint]
                    and self._g.degree(endpoint) == 0
                ):
                    self._g.remove_node(endpoint)

        self.dangling_edges = dangling

        if dangling:
            preview = ", ".join(f"{e.src}->{e.dst}" for e in dangling[:5])
            more = f" (+{len(dangling) - 5} more)" if len(dangling) > 5 else ""
            msg = f"{len(dangling)} dangling edge(s) dropped: {preview}{more}"
            if strict:
                raise GraphValidationError(msg)
            log.warning(msg)

        return dangling

    # ------------------------------------------------------------------ #
    # Debug helpers
    # ------------------------------------------------------------------ #
    def describe(self) -> Dict[str, Any]:
        """Snapshot for logging: vertex count by owner + edge count."""
        by_owner: Dict[str, int] = {}
        for v in self.vertices():
            by_owner[v.owner or "<unowned>"] = by_owner.get(v.owner or "<unowned>", 0) + 1
        return {
            "vertices": len(self._g),
            "edges": self._g.number_of_edges(),
            "by_owner": by_owner,
            "dangling_dropped": len(self.dangling_edges),
        }

    def __repr__(self) -> str:
        d = self.describe()
        return f"<GameGraph V={d['vertices']} E={d['edges']} owners={d['by_owner']}>"
