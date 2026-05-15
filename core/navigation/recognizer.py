"""
`ScreenRecognizer` — answer "which vertex are we currently on?"

The graph stores recognizers as opaque values (the rule lives in
`Vertex.recognizer`). `ScreenRecognizer` coerces each into a callable
``(screenshot) -> bool``:

* `Button`   -> `backend.is_visible(button)` (well, equivalent via matcher).
* `str`      -> `Button.simple(name)` and then the Button rule.
* callable   -> called directly. Two signatures are accepted:
  ``(screenshot) -> bool`` and ``(screenshot, matcher) -> bool``. The
  two-argument form lets composite recognizers run multiple
  ``matcher.find(...)`` checks without having to closure-capture a matcher
  at graph-build time (when the per-account matcher isn't available yet).
* anything else -> `TypeError`.

We don't memoize the resolved callable on the Vertex because Vertex is a
frozen dataclass — instead we maintain an internal cache keyed by vertex id.

Returning the *first* match is intentional. UI states should be mutually
exclusive on a real game, and ambiguity is a graph bug. We log a warning
when more than one recognizer fires on the same screenshot so the
developer notices.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from core.logging_config import get_logger
from core.navigation.graph import GameGraph
from core.vision.button import Button
from core.vision.template_matcher import TemplateMatcher

log = get_logger(__name__)


# A normalized recognizer callable: takes a BGR screenshot, returns True
# iff the screen corresponds to the vertex this callable was bound to.
NormalizedRecognizer = Callable[[np.ndarray], bool]


class ScreenRecognizer:
    """Map screenshots to vertex ids using the per-vertex recognizers."""

    def __init__(
        self,
        matcher: Optional[TemplateMatcher] = None,
    ) -> None:
        # Matcher is needed when a Vertex.recognizer is a Button/str. We
        # accept None so callers without a backend yet (tests) can still
        # build an instance.
        self._matcher = matcher or TemplateMatcher()
        self._resolved: Dict[str, NormalizedRecognizer] = {}

    @property
    def matcher(self) -> TemplateMatcher:
        return self._matcher

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def detect_current(
        self,
        screenshot: np.ndarray,
        graph: GameGraph,
    ) -> Optional[str]:
        """Identify the active vertex on this screenshot.

        Args:
            screenshot: BGR ``(H, W, 3)`` uint8 array (the canonical form
                produced by `InputBackend.screenshot`).
            graph: The assembled graph to scan.

        Returns:
            The fully-qualified id of the first matching vertex, or None if
            no vertex's recognizer fired. Multiple matches log a warning
            (UI ambiguity is almost always a bug) but only the first is
            returned.
        """
        hits: List[str] = []
        for v in graph.vertices():
            if v.recognizer is None:
                continue
            try:
                rec = self._resolve(v.id, v.recognizer)
            except TypeError as e:
                log.warning("vertex %r recognizer is invalid: %s", v.id, e)
                continue
            try:
                if rec(screenshot):
                    hits.append(v.id)
                    if len(hits) >= 2:
                        # Already ambiguous — break early but log all the matches.
                        break
            except Exception as exc:  # noqa: BLE001 — user-supplied callable
                log.warning("vertex %r recognizer raised: %s", v.id, exc)

        if len(hits) > 1:
            log.warning(
                "ambiguous recognition: multiple vertices fired: %s; "
                "returning %r — fix overlapping recognizers",
                hits,
                hits[0],
            )
        return hits[0] if hits else None

    def invalidate(self, vertex_id: Optional[str] = None) -> None:
        """Drop the cached resolved callable for `vertex_id`, or all of them."""
        if vertex_id is None:
            self._resolved.clear()
        else:
            self._resolved.pop(vertex_id, None)

    # ------------------------------------------------------------------ #
    # Coercion: opaque recognizer -> callable
    # ------------------------------------------------------------------ #
    def _resolve(self, vid: str, raw: Any) -> NormalizedRecognizer:
        cached = self._resolved.get(vid)
        if cached is not None:
            return cached
        resolved = self._coerce(raw)
        self._resolved[vid] = resolved
        return resolved

    def _coerce(self, raw: Any) -> NormalizedRecognizer:
        # Order matters: callable comes after the dataclass check because
        # frozen dataclasses are also callable (they call __init__).
        if isinstance(raw, Button):
            return self._button_recognizer(raw)
        if isinstance(raw, str):
            return self._button_recognizer(Button.simple(raw))
        if callable(raw):
            return self._wrap_callable(raw)
        raise TypeError(
            f"recognizer must be a Button, str template name, or callable, "
            f"got {type(raw).__name__}"
        )

    def _wrap_callable(self, fn: Callable[..., Any]) -> NormalizedRecognizer:
        # Composite recognizers (`AND NOT`, etc.) often need to run several
        # `matcher.find(...)` calls — passing the matcher in here means the
        # plugin author doesn't have to capture one at graph-build time,
        # where the per-account matcher isn't available yet.
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            # C-implemented callables without an inspectable signature: fall
            # back to the single-arg convention.
            return lambda shot: bool(fn(shot))
        required = sum(
            1
            for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            and p.default is p.empty
        )
        if required >= 2:
            matcher = self._matcher
            return lambda shot: bool(fn(shot, matcher))
        return lambda shot: bool(fn(shot))

    def _button_recognizer(self, button: Button) -> NormalizedRecognizer:
        matcher = self._matcher

        def recognize(shot: np.ndarray) -> bool:
            return matcher.find(shot, button) is not None

        return recognize
