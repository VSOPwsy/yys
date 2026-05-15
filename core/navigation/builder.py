"""
DSL helpers for writing graphs by hand.

Pattern
-------
A graph "module" is a function that opens a `subgraph()` (or `root_graph()`)
context and calls `vertex(...)` / `edge(...)` inside it::

    def build_subgraph():
        with subgraph("daily_reward") as g:
            vertex("entry", recognizer=ENTRY_ANCHOR)
            vertex("reward_list", recognizer=LIST_ANCHOR)
            edge("entry", "reward_list", action=click_button(LIST_BTN), cost=1.0)
            edge("reward_list", "main.main_menu",
                 action=click_button(BACK_BTN), cost=1.2)
        return g

Inside the context, `vertex("entry")` is recorded as the qualified id
``daily_reward.entry`` because `subgraph()` set the active namespace. Edge
references work the same way except that a name containing ``.`` (or wrapped
in `external(...)`) is treated as absolute and left alone — that is how
plugins point at vertices owned by another namespace.

Action factories
----------------
Every factory in this module returns a `Callable[[NavigationContext], None]`
suitable for `Edge.action`. They share one assumption: the navigation
context exposes a `.backend` attribute conforming to `InputBackend`. The
factories never store mutable state, so it is safe to reuse a single action
across multiple edges — but each edge should have its own factory call if
you might want per-edge tweaks.

Why a context object instead of "just the backend"
--------------------------------------------------
Phase 3 will need to pass per-account cache handles, plugin scope, and a
stop event into actions. Threading those through every factory now would
be churn; the context object means the factory signature does not change
when we add fields.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, List, Optional, Tuple, Union

from core.exceptions import GraphValidationError
from core.humanize import random_point_in_rect
from core.logging_config import get_logger
from core.navigation.graph import Action, GameGraph, Recognizer
from core.vision.button import Button

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Navigation context (the single argument every action receives)
# --------------------------------------------------------------------------- #
@dataclass
class NavigationContext:
    """Bag of state passed to every edge action.

    Phase 2 only needs `.backend`. Future phases will append fields
    (`cache`, `stop_event`, `plugin_scope`, ...) — keeping this object lets
    us extend the contract without re-touching every action factory.
    """

    backend: Any  # core.input_backend.base.InputBackend, but typing.Any to avoid import cycle
    extras: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.extras is None:
            self.extras = {}


# --------------------------------------------------------------------------- #
# `external(...)` — explicit "this reference is absolute"
# --------------------------------------------------------------------------- #
class _External:
    """Wrapper that tells the DSL not to namespace this reference.

    Use the `external()` factory rather than instantiating this directly.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("external(name) requires a non-empty name")
        self.name = name

    def __repr__(self) -> str:
        return f"external({self.name!r})"


def external(name: str) -> _External:
    """Mark a vertex reference as absolute inside a `subgraph()` block.

    Inside a subgraph, bare names get the namespace prefix and dotted names
    are kept verbatim. `external("main_menu")` is a third option: a name
    without a dot that still must NOT be prefixed. Useful when the target
    happens to live in the root namespace and you want the call site to
    say so explicitly.
    """
    return _External(name)


VertexRef = Union[str, _External]


# --------------------------------------------------------------------------- #
# Subgraph builder + thread-local context stack
# --------------------------------------------------------------------------- #
class SubgraphBuilder:
    """Holds the active target graph and namespace while a context is open.

    Internal — most callers should not construct one. The public surface is
    `subgraph()` / `root_graph()`.
    """

    def __init__(self, graph: GameGraph, namespace: Optional[str]) -> None:
        self.graph = graph
        self.namespace = namespace
        # When non-None, vertex() defaults `owner=` to this value. The root
        # graph passes "main" so the demo / runtime can distinguish "shared
        # root vertex" from "plugin-owned vertex" without an extra kwarg at
        # every call.
        self.default_owner: Optional[str] = "main" if namespace is None else namespace

    def qualify(self, ref: VertexRef) -> str:
        """Resolve a DSL-level vertex reference to a fully-qualified id."""
        if isinstance(ref, _External):
            return ref.name
        if "." in ref:
            return ref
        if self.namespace is None:
            return ref
        return f"{self.namespace}.{ref}"


class _ContextStack(threading.local):
    """Thread-local stack of active SubgraphBuilders.

    A stack (not just a single slot) so a user can nest subgraphs while
    importing modules that themselves build graphs without blowing up.
    """

    def __init__(self) -> None:
        self.stack: List[SubgraphBuilder] = []


_CONTEXT = _ContextStack()


def _current() -> SubgraphBuilder:
    if not _CONTEXT.stack:
        raise GraphValidationError(
            "vertex()/edge() called outside a subgraph()/root_graph() context"
        )
    return _CONTEXT.stack[-1]


@contextmanager
def subgraph(
    name: str,
    *,
    graph: Optional[GameGraph] = None,
) -> Iterator[GameGraph]:
    """Open a builder context for a plugin subgraph.

    Args:
        name: The plugin namespace, e.g. "daily_reward". Bare-name vertex /
            edge references inside this block get prefixed with `name.`.
        graph: Reuse an existing `GameGraph`. Defaults to a fresh one. A
            test that wants to inspect side effects can pass its own.

    Yields:
        The target `GameGraph` so the caller can `return g`.

    Raises:
        ValueError: `name` is empty (use `root_graph()` for the no-namespace
            root graph).
    """
    if not name:
        raise ValueError("subgraph(name) requires a non-empty name; "
                         "use root_graph() for the root graph")
    g = graph or GameGraph()
    _CONTEXT.stack.append(SubgraphBuilder(g, name))
    try:
        yield g
    finally:
        _CONTEXT.stack.pop()


@contextmanager
def root_graph(*, graph: Optional[GameGraph] = None) -> Iterator[GameGraph]:
    """Open a builder context for the root (no-namespace) graph.

    Inside this block, bare names are not prefixed. Use it for `graphs/main.py`.
    Vertices default to ``owner="main"``.
    """
    g = graph or GameGraph()
    _CONTEXT.stack.append(SubgraphBuilder(g, None))
    try:
        yield g
    finally:
        _CONTEXT.stack.pop()


# --------------------------------------------------------------------------- #
# DSL: vertex / edge
# --------------------------------------------------------------------------- #
def vertex(
    id: str,
    *,
    name: Optional[str] = None,
    recognizer: Recognizer = None,
    dwell_time: int = 500,
    owner: Optional[str] = None,
) -> str:
    """Record a vertex in the active subgraph.

    Returns the qualified id that was registered (useful for tests).

    Args mirror `GameGraph.add_vertex`. The `owner` field defaults to the
    builder's default ("main" for root_graph, the namespace for subgraph);
    pass it explicitly only to override.
    """
    ctx = _current()
    qualified = ctx.qualify(id)
    ctx.graph.add_vertex(
        qualified,
        name=name,
        recognizer=recognizer,
        dwell_time=dwell_time,
        owner=owner if owner is not None else ctx.default_owner,
    )
    return qualified


def edge(
    from_id: VertexRef,
    to_id: VertexRef,
    *,
    action: Action,
    cost: float = 1.0,
    risky: bool = False,
    tags: Optional[Iterable[str]] = None,
    cooldown: float = 0.0,
) -> Tuple[str, str]:
    """Record an edge in the active subgraph.

    `from_id` / `to_id` go through the active builder's namespace rules:
    bare -> prefix; contains "."; or `external()` -> verbatim.

    Returns the resolved ``(src, dst)`` pair so tests / debugging code can
    confirm what got registered.
    """
    ctx = _current()
    src = ctx.qualify(from_id)
    dst = ctx.qualify(to_id)
    ctx.graph.add_edge(
        src,
        dst,
        action=action,
        cost=cost,
        risky=risky,
        tags=tags,
        cooldown=cooldown,
    )
    return src, dst


# --------------------------------------------------------------------------- #
# Action factories
# --------------------------------------------------------------------------- #
def click_button(button: Button) -> Action:
    """Action that taps a `Button` on the current screen.

    Delegates to `backend.click(button)`, which raises `MatchTimeout` if the
    button is not visible. We do not catch that — the Navigator is the right
    place to translate a failed action into `EdgeExecutionFailed`.
    """

    def _action(ctx: NavigationContext) -> None:
        ctx.backend.click(button)

    _action.__name__ = f"click_button({button.display_name})"
    return _action


def click_button_with_expand(
    button: Button,
    expand_region: Tuple[int, int, int, int],
    *,
    wait_after_expand: float = 1.0,
    randomize: bool = True,
) -> Action:
    """Click ``button``. If it's not visible, tap inside ``expand_region``
    first, wait, then click.

    Motivation:
        PathFinder builds a sequence of edges and `Navigator` walks them
        in order. Some target buttons live inside a collapsible UI panel —
        they're hidden until the panel is expanded by tapping a hot zone
        with no template-able visual. Modeling each (collapsed, expanded)
        cross-product as a separate vertex blows up to ``2^N`` for ``N``
        independent folds, so instead we attach the fold-handling at the
        *edge* — let the action verify visibility, expand on demand, then
        click. PathFinder stays oblivious; plugin step code stays
        oblivious; the knowledge lives at exactly one place: the edge
        that needs to click a folded button.

    Behavior:
        1. ``backend.find(button)`` — if it returns a hit, just
           ``backend.click(button)`` and we're done.
        2. Otherwise: ``random_point_in_rect(expand_region)`` picks a
           uniformly random point inside the hotspot rect, then
           ``backend.click_xy(x, y, randomize=randomize)`` taps it.
           Backend ``_jitter`` (typically ±3 px) stacks on top for micro
           noise.
        3. ``time.sleep(wait_after_expand)`` — wait for the fold-out
           animation to settle.
        4. ``backend.click(button)`` — this calls ``find`` internally; if
           the button still isn't visible (wrong hotspot, animation too
           slow, button just isn't in this fold), `MatchTimeout`
           propagates → `Navigator` translates to `EdgeExecutionFailed`
           and replans.

    Args:
        button: The target button to click after expansion.
        expand_region: ``(x1, y1, x2, y2)`` ADB rect to tap-inside when
            ``button`` is hidden. See `random_point_in_rect` for
            validation.
        wait_after_expand: Seconds to sleep after the expand tap. Default
            1.0; tune up if the fold-out animation is slow.
        randomize: Forwarded to the backend's ``click_xy`` for the expand
            tap (the final ``click(button)`` always randomizes via the
            base ``_jitter_in_button`` path).

    Raises:
        ValueError: `wait_after_expand < 0`, or `expand_region` malformed
            (propagated from `random_point_in_rect`).
        MatchTimeout: Button still invisible after expand + wait
            (propagates from `backend.click`).

    Returns:
        An action suitable for `Edge.action`.
    """
    if wait_after_expand < 0:
        raise ValueError(
            f"wait_after_expand must be >= 0, got {wait_after_expand}"
        )

    def _action(ctx: NavigationContext) -> None:
        if ctx.backend.find(button) is None:
            log.info(
                "click_button_with_expand: %s not visible; tapping expand "
                "region %s and waiting %.2fs",
                button.display_name,
                expand_region,
                wait_after_expand,
            )
            x, y = random_point_in_rect(expand_region)
            ctx.backend.click_xy(x, y, randomize=randomize)
            time.sleep(wait_after_expand)
        ctx.backend.click(button)

    _action.__name__ = f"click_button_with_expand({button.display_name})"
    return _action


def click_at(x: int, y: int, *, randomize: bool = True) -> Action:
    """Action that taps a fixed pixel. Use sparingly — prefer `click_button`.

    `graph_composer` emits this when the user picks the "click_at" edge type;
    in production you should still try to capture a template and replace it.
    """

    def _action(ctx: NavigationContext) -> None:
        ctx.backend.click_xy(x, y, randomize=randomize)

    _action.__name__ = f"click_at({x},{y})"
    return _action


def swipe_to(
    start: Tuple[int, int],
    end: Tuple[int, int],
    duration: float = 0.3,
) -> Action:
    """Action that swipes between two explicit screen points."""
    if duration <= 0:
        raise ValueError(f"swipe duration must be > 0, got {duration}")

    def _action(ctx: NavigationContext) -> None:
        ctx.backend.swipe(start, end, duration)

    _action.__name__ = f"swipe_to({start}->{end})"
    return _action


def swipe_dir(
    direction: str,
    distance: int = 300,
    duration: float = 0.3,
) -> Action:
    """Action that swipes from screen center in a cardinal direction.

    Args:
        direction: One of "up", "down", "left", "right".
        distance: How many pixels to swipe (positive).
        duration: Swipe duration in seconds.

    The start point is the *centre of the current screenshot*, computed at
    action time so we don't need to hard-code resolution.
    """
    deltas = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    if direction not in deltas:
        raise ValueError(
            f"swipe_dir direction must be one of {sorted(deltas)}, got {direction!r}"
        )
    if distance <= 0:
        raise ValueError(f"swipe_dir distance must be > 0, got {distance}")
    if duration <= 0:
        raise ValueError(f"swipe_dir duration must be > 0, got {duration}")
    dx, dy = deltas[direction]

    def _action(ctx: NavigationContext) -> None:
        shot = ctx.backend.screenshot()
        h, w = shot.shape[:2]
        cx, cy = w // 2, h // 2
        ctx.backend.swipe((cx, cy), (cx + dx * distance, cy + dy * distance), duration)

    _action.__name__ = f"swipe_dir({direction},{distance})"
    return _action


def press_back() -> Action:
    """Action that presses the Android back / system-escape key.

    Concrete backends implement this through their own keyevent channel.
    `NemuIpcBackend` does not currently support it (nemu's DLL exposes
    touch only) — use `click_button(your_back_button)` for now if you are
    on nemu.
    """

    def _action(ctx: NavigationContext) -> None:
        ctx.backend.press_back()

    _action.__name__ = "press_back()"
    return _action


def wait(seconds: float) -> Action:
    """Action that just sleeps. Models "the UI transitions on its own".

    Common case: a loading screen that finishes after ~N seconds.
    """
    if seconds < 0:
        raise ValueError(f"wait seconds must be >= 0, got {seconds}")

    def _action(ctx: NavigationContext) -> None:
        time.sleep(seconds)

    _action.__name__ = f"wait({seconds:.2f}s)"
    return _action


def compose(*actions: Action) -> Action:
    """Run several actions in order. Stops on the first exception."""
    if not actions:
        raise ValueError("compose() requires at least one action")

    def _action(ctx: NavigationContext) -> None:
        for sub in actions:
            sub(ctx)

    names = ",".join(getattr(a, "__name__", "?") for a in actions)
    _action.__name__ = f"compose({names})"
    return _action


def conditional(
    predicate: Callable[[NavigationContext], bool],
    then_action: Action,
    else_action: Optional[Action] = None,
) -> Action:
    """Branch on a runtime predicate.

    Args:
        predicate: ``ctx -> bool``. Typically ``lambda ctx: ctx.backend.is_visible(BTN)``.
        then_action: Runs when the predicate returns True.
        else_action: Optional fallback when the predicate returns False.
    """

    def _action(ctx: NavigationContext) -> None:
        if predicate(ctx):
            then_action(ctx)
        elif else_action is not None:
            else_action(ctx)

    _action.__name__ = "conditional(...)"
    return _action
