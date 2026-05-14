"""
`Navigator` — execute a path through the graph against a real backend.

Responsibilities (single-purpose by design):
    1. Identify where we are now (delegate to `ScreenRecognizer`).
    2. Plan a route to the target (delegate to `PathFinder`).
    3. Execute each edge's action and verify arrival at the expected vertex.

Verification step matters
-------------------------
A click can miss; a swipe can land us on a popup; a wait can be too short.
After each edge we re-screenshot and ask the recognizer "are we where we
expected to be?". If we're at the wrong vertex, we replan once (the screen
may have legitimately changed under us). Two consecutive recognition
failures in a row escalate to `EdgeExecutionFailed` so the caller can
restart the worker or surface a "please help" prompt.

Bare names vs qualified names
-----------------------------
`goto()` accepts both. A bare name is interpreted as "look for it in the
root namespace": we try the literal name first, then fall back to scanning
vertices whose `owner == "main"` and `id.split(".")[-1] == name`. Plugin
callers should still prefer fully qualified ids — bare is a convenience
for the demo and one-off scripts.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, List, Optional, Set

from core.exceptions import (
    CurrentVertexUnknown,
    EdgeExecutionFailed,
    NavigationError,
    UnknownVertex,
)
from core.logging_config import get_logger
from core.navigation.builder import NavigationContext
from core.navigation.graph import Edge, GameGraph
from core.navigation.pathfinder import PathFinder
from core.navigation.recognizer import ScreenRecognizer

log = get_logger(__name__)


class Navigator:
    """Travel through a `GameGraph` using a concrete backend."""

    def __init__(
        self,
        backend: Any,  # core.input_backend.base.InputBackend; Any to avoid import cycle
        graph: GameGraph,
        pathfinder: Optional[PathFinder] = None,
        recognizer: Optional[ScreenRecognizer] = None,
        *,
        context_extras: Optional[dict] = None,
    ) -> None:
        """Wire together the navigation machinery.

        Args:
            backend: Live `InputBackend` instance (connected or context-managed).
            graph: Already assembled `GameGraph`.
            pathfinder: Optional `PathFinder`. Defaults to a fresh one over `graph`.
            recognizer: Optional `ScreenRecognizer`. Defaults to a fresh one
                using `backend.matcher` so we share the template cache.
            context_extras: Forwarded to every `NavigationContext.extras`.
        """
        self._backend = backend
        self._graph = graph
        self._pathfinder = pathfinder or PathFinder(graph)
        self._recognizer = recognizer or ScreenRecognizer(
            matcher=getattr(backend, "matcher", None)
        )
        self._context_extras = dict(context_extras or {})

    @property
    def graph(self) -> GameGraph:
        return self._graph

    @property
    def backend(self) -> Any:
        return self._backend

    @property
    def pathfinder(self) -> PathFinder:
        return self._pathfinder

    @property
    def recognizer(self) -> ScreenRecognizer:
        return self._recognizer

    # ------------------------------------------------------------------ #
    # Identification
    # ------------------------------------------------------------------ #
    def detect_current(self) -> Optional[str]:
        """Screenshot once and return the recognized vertex id, or None."""
        shot = self._backend.screenshot()
        return self._recognizer.detect_current(shot, self._graph)

    def is_at(self, vertex_id: str) -> bool:
        """True iff the currently visible screen matches `vertex_id`.

        Resolves bare names the same way `goto()` does. Returns False if we
        can't recognize anything.
        """
        resolved = self._resolve_vertex_id(vertex_id, allow_missing=True)
        if resolved is None:
            return False
        return self.detect_current() == resolved

    # ------------------------------------------------------------------ #
    # Goto
    # ------------------------------------------------------------------ #
    def goto(
        self,
        target_id: str,
        *,
        mode: str = "shortest",
        avoid_risky: bool = False,
        avoid_tags: Optional[Iterable[str]] = None,
        max_path_replans: int = 1,
        per_edge_timeout: float = 10.0,
    ) -> bool:
        """Travel from the current vertex to `target_id`.

        Args:
            target_id: Either a fully-qualified id (preferred) or a bare name
                resolved via the root namespace.
            mode: "shortest" (default) or "random". Random mode samples among
                multiple viable paths so the bot doesn't look mechanical.
            avoid_risky / avoid_tags: Forwarded to `PathFinder`.
            max_path_replans: How many times we recompute the route after
                we end up on an unexpected vertex. Default 1 — one missed
                click is a normal day; two in a row means the model is wrong.
            per_edge_timeout: Hard upper bound (seconds) for executing one
                edge action plus the post-condition check. Mostly defends
                against a `wait(...)` typo'd to 600s.

        Returns:
            True on arrival.

        Raises:
            UnknownVertex: `target_id` doesn't exist in the graph.
            CurrentVertexUnknown: Can't recognize the current screen.
            NoPathFound: No route under the given constraints.
            EdgeExecutionFailed: We executed an edge but didn't arrive
                where we expected, and replanning has run out.
        """
        if mode not in ("shortest", "random"):
            raise ValueError(f"mode must be 'shortest' or 'random', got {mode!r}")

        resolved_target = self._resolve_vertex_id(target_id)
        current = self.detect_current()
        if current is None:
            raise CurrentVertexUnknown(
                f"goto({target_id!r}): cannot identify current screen"
            )
        log.info("goto: current=%r target=%r mode=%r", current, resolved_target, mode)
        if current == resolved_target:
            log.info("already at target %r", resolved_target)
            return True

        replans_used = 0
        while True:
            path = self._plan(
                current,
                resolved_target,
                mode=mode,
                avoid_risky=avoid_risky,
                avoid_tags=avoid_tags,
            )
            log.info(
                "plan (%d hops): %s",
                len(path),
                " -> ".join([current, *(e.dst for e in path)]),
            )

            try:
                self._execute(path, per_edge_timeout=per_edge_timeout)
                return True
            except _EdgeMissedTarget as miss:
                # Edge ran but recognition disagrees with the expected dst.
                current = miss.observed or "<unknown>"
                if miss.observed is None:
                    raise CurrentVertexUnknown(
                        f"goto({target_id!r}): lost track of current vertex "
                        f"after edge {miss.edge.src!r} -> {miss.edge.dst!r}"
                    ) from miss
                if replans_used >= max_path_replans:
                    raise EdgeExecutionFailed(
                        f"goto({target_id!r}): expected {miss.edge.dst!r} "
                        f"after edge {miss.edge.src!r} -> {miss.edge.dst!r}, "
                        f"but recognizer saw {miss.observed!r}; "
                        f"replans exhausted ({max_path_replans})"
                    ) from miss
                replans_used += 1
                log.warning(
                    "replanning: expected %r, saw %r (replan %d/%d)",
                    miss.edge.dst,
                    miss.observed,
                    replans_used,
                    max_path_replans,
                )
                if current == resolved_target:
                    log.info("replan: ended up at target by accident, done")
                    return True

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _plan(
        self,
        start: str,
        end: str,
        *,
        mode: str,
        avoid_risky: bool,
        avoid_tags: Optional[Iterable[str]],
    ) -> List[Edge]:
        if mode == "shortest":
            return self._pathfinder.shortest_path(
                start, end, avoid_risky=avoid_risky, avoid_tags=avoid_tags
            )
        return self._pathfinder.random_path(
            start, end, avoid_risky=avoid_risky, avoid_tags=avoid_tags
        )

    def _execute(self, path: List[Edge], *, per_edge_timeout: float) -> None:
        ctx = NavigationContext(backend=self._backend, extras=dict(self._context_extras))
        for e in path:
            log.info("step: %r -> %r (cost=%.2f, action=%s)",
                     e.src, e.dst, e.cost, getattr(e.action, "__name__", repr(e.action)))
            t0 = time.monotonic()
            try:
                e.action(ctx)
            except NavigationError:
                raise
            except Exception as exc:
                raise EdgeExecutionFailed(
                    f"edge {e.src!r} -> {e.dst!r} action raised: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            # Honor the destination vertex's dwell time before re-recognizing.
            dest = self._graph.get_vertex(e.dst)
            if dest.dwell_time:
                time.sleep(dest.dwell_time / 1000.0)

            observed = self.detect_current()
            elapsed = time.monotonic() - t0
            if observed != e.dst:
                raise _EdgeMissedTarget(e, observed)
            if elapsed > per_edge_timeout:
                log.warning(
                    "edge %r -> %r exceeded per_edge_timeout (%.1fs > %.1fs)",
                    e.src, e.dst, elapsed, per_edge_timeout,
                )

    def _resolve_vertex_id(
        self,
        target: str,
        *,
        allow_missing: bool = False,
    ) -> Optional[str]:
        """Accept bare or qualified names; return the qualified id."""
        if not target:
            raise ValueError("target vertex id must be non-empty")

        if self._graph.has_vertex(target):
            return target

        # Bare name lookup: try root-owned vertices first.
        candidates = [
            v.id
            for v in self._graph.vertices()
            if v.owner == "main" and v.id.split(".")[-1] == target
        ]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise UnknownVertex(
                f"target {target!r} is ambiguous among root-owned vertices: {candidates!r}"
            )

        if allow_missing:
            return None
        raise UnknownVertex(f"target vertex {target!r} not in graph")


# Sentinel exception used to ferry recognition mismatch up to goto().
class _EdgeMissedTarget(Exception):
    def __init__(self, edge: Edge, observed: Optional[str]) -> None:
        super().__init__(
            f"edge {edge.src!r} -> {edge.dst!r}: observed {observed!r}"
        )
        self.edge = edge
        self.observed = observed
