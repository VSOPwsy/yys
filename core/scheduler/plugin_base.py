"""
`GameplayPlugin` + `PluginContext` — the gameplay-side contract.

Every concrete plugin lives under `plugins/<name>/` and exports:

  * a module-level `build_subgraph() -> GameGraph` (in `graph.py`) that
    defines this plugin's namespaced vertices and edges,
  * a `GameplayPlugin` subclass (typically in `<name>_plugin.py` or
    `__init__.py`) that re-exports `build_subgraph` as a classmethod and
    implements the `setup` / `run` / `teardown` lifecycle.

The `PluginRegistry` discovers these classes at startup, and the
`Scheduler` instantiates one `PluginWorker` per `(account_id, plugin)`
combination — each gets its own `PluginContext`. No singleton sharing
between accounts (CLAUDE.md S5).
"""

from __future__ import annotations

import abc
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, ClassVar, List, Optional, TYPE_CHECKING

from core.logging_config import get_logger

if TYPE_CHECKING:  # pragma: no cover — imports for type hints only
    from core.cache.manager import CacheManager
    from core.input_backend.base import InputBackend
    from core.navigation.graph import GameGraph
    from core.navigation.navigator import Navigator
    from core.vision.ocr import OcrEngine
    from core.vision.template_matcher import TemplateMatcher


@dataclass
class PluginContext:
    """Everything a plugin's `run()` needs to interact with the game.

    Constructed by `Scheduler` per `(account_id, plugin_name)` and passed
    to all lifecycle hooks. The plugin must NOT capture references to
    fields across `setup` / `run` / `teardown` calls unless it understands
    that the same context is reused; the events are wired to the same
    threading.Event instances, so capturing `should_stop` once is fine.

    Fields:
        account_id: Stable identifier, used for log prefixes and cache
            isolation. Required.
        backend: Per-account `InputBackend` (already connected).
        navigator: Per-account `Navigator` over the assembled graph.
        matcher: `TemplateMatcher`. Shared across plugins on the same
            account (templates are immutable).
        ocr: Process-wide `OcrEngine` singleton (None until first
            requested if not pre-warmed).
        cache: Per-account `CacheManager`.
        logger: A `logging.Logger` whose name embeds `account_id` for
            grep-friendly log output.
        extras: Free-form dict; plugins can stash plugin-private state
            here, but anything cross-plugin should go through `cache`.
    """

    account_id: str
    backend: "InputBackend"
    navigator: "Navigator"
    matcher: "TemplateMatcher"
    ocr: Optional["OcrEngine"]
    cache: "CacheManager"
    logger: logging.Logger
    extras: dict = field(default_factory=dict)
    # Events live on the context so the plugin code can ask "should I stop?"
    # without reaching back into the worker. Set by the worker on construction.
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _pause_event: threading.Event = field(default_factory=threading.Event)

    def should_stop(self) -> bool:
        """True iff the worker has been asked to stop.

        Plugin `run()` MUST poll this regularly — at minimum once per
        outer-loop iteration, ideally before any long-running primitive.
        """
        return self._stop_event.is_set()

    def should_pause(self) -> bool:
        """True iff the worker is currently in pause state.

        Plugin authors typically combine this with `sleep()` to idle
        cleanly until the user resumes.
        """
        return self._pause_event.is_set()

    def sleep(self, seconds: float) -> bool:
        """Sleep up to `seconds`, returning early if stop is requested.

        Args:
            seconds: Maximum wait, in seconds. `<= 0` returns immediately.

        Returns:
            True if the sleep was interrupted by `stop()`; False if the
            full duration elapsed (or `seconds <= 0`).
        """
        if seconds <= 0:
            return self._stop_event.is_set()
        # Event.wait returns True iff the flag was set during the wait.
        return self._stop_event.wait(timeout=seconds)

    def wait_until_resumed(self, *, poll: float = 0.2) -> bool:
        """Block until `should_pause()` becomes False, or stop is requested.

        Args:
            poll: Granularity for re-checking stop. Smaller = quicker
                reaction to stop signal at higher CPU cost.

        Returns:
            True if we exited because stop was requested; False if we
            exited because pause was cleared.
        """
        while self._pause_event.is_set():
            if self._stop_event.wait(timeout=poll):
                return True
        return False


class GameplayPlugin(abc.ABC):
    """Abstract base class for a single gameplay loop (one game mode).

    Class attributes (subclass MUST override):
        name: Unique identifier, also the namespace prefix in the graph
            (e.g. ``"daily_quest"`` makes the plugin's vertices live at
            ``daily_quest.*``). Lowercase + underscores, no dots.
        display_name: Human-readable label shown in UIs / logs.
        requires_vertices: Fully-qualified vertex ids the plugin's `run()`
            assumes will exist. The scheduler verifies these against the
            assembled graph before starting the worker, raising
            `PluginRequirementUnmet` if any are missing — this is the
            safety net for "I forgot to enable plugin B that plugin A
            depends on".

    Subclass MUST implement:
        * `build_subgraph()` — classmethod returning a `GameGraph`. The
          canonical pattern is to delegate to a top-level `build_subgraph`
          in the plugin package's `graph.py` (see `plugins/_demo`).
        * `setup(self, ctx)` — one-shot before `run`. Use for warm-up
          (loading templates, parsing plugin config), NOT for the work
          itself.
        * `run(self, ctx)` — the loop. Must poll `ctx.should_stop()` /
          `ctx.should_pause()` regularly. Returning normally signals
          "I'm done" and the worker transitions to STOPPED.
        * `teardown(self, ctx)` — one-shot cleanup, always called even
          if `run()` raises. Safe to be a no-op.

    Optional hooks:
        * `on_pause(self, ctx)` — called once when pause is requested,
          before the next pause-poll. Default: no-op.
        * `on_resume(self, ctx)` — called once when pause is cleared.
          Default: no-op.

    Threading model: there is exactly one `PluginWorker` per
    `(account_id, plugin)` pair. The worker thread is the *only* one
    that calls `setup` / `run` / `teardown` / `on_pause` / `on_resume`.
    Plugin authors do NOT need to lock state owned by the instance.
    """

    name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    requires_vertices: ClassVar[List[str]] = []

    def __init__(self) -> None:
        cls = type(self)
        if not cls.name:
            raise TypeError(
                f"{cls.__name__}.name must be a non-empty class attribute"
            )
        if "." in cls.name:
            raise ValueError(
                f"{cls.__name__}.name ({cls.name!r}) must not contain '.'; "
                f"it is used as a graph namespace"
            )
        if not cls.display_name:
            cls.display_name = cls.name

    # ------------------------------------------------------------------ #
    # Subgraph contract
    # ------------------------------------------------------------------ #
    @classmethod
    @abc.abstractmethod
    def build_subgraph(cls) -> "GameGraph":
        """Return this plugin's subgraph (unmerged, namespace-internal).

        Convention: implement in `plugins/<name>/graph.py` as a top-level
        function, then in the plugin class do::

            @classmethod
            def build_subgraph(cls):
                from plugins.foo.graph import build_subgraph
                return build_subgraph()

        Called by `PluginRegistry.collect_subgraphs()` at scheduler
        startup, before any worker thread is spawned.
        """

    # ------------------------------------------------------------------ #
    # Lifecycle (abstract — subclass must implement)
    # ------------------------------------------------------------------ #
    @abc.abstractmethod
    def setup(self, ctx: PluginContext) -> None:
        """One-shot prep before `run`. Worker thread calls this exactly once."""

    @abc.abstractmethod
    def run(self, ctx: PluginContext) -> None:
        """Main loop. Poll `ctx.should_stop()` / `ctx.should_pause()` often.

        Returning normally = "I finished, no more work". Worker will then
        call `teardown` and transition to STOPPED. Raising a `BotError`
        subclass is captured into `worker.last_error` and the worker
        transitions to ERROR. Raising anything else also lands in ERROR
        but is logged with full traceback.
        """

    @abc.abstractmethod
    def teardown(self, ctx: PluginContext) -> None:
        """Cleanup. Always called, even if `run` raised. Should be idempotent."""

    # ------------------------------------------------------------------ #
    # Optional hooks (default = no-op)
    # ------------------------------------------------------------------ #
    def on_pause(self, ctx: PluginContext) -> None:
        """Called once when the pause flag is set, before plugin notices."""

    def on_resume(self, ctx: PluginContext) -> None:
        """Called once when the pause flag is cleared."""

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"


def make_logger(account_id: str, plugin_name: str) -> logging.Logger:
    """Build the convention-compliant logger for a `(account, plugin)` pair.

    Used by `Scheduler` when constructing `PluginContext` so all plugin
    log records carry both identifiers and can be filtered/grepped.
    """
    return get_logger(f"plugin.{account_id}.{plugin_name}")
