"""
Project-wide exception hierarchy.

All predictable runtime failures must raise a subclass of `BotError`. Direct
`raise Exception(...)` is forbidden (see CLAUDE.md S3 exception discipline).

Hierarchy
---------
    BotError
    +-- InputBackendError
    |   +-- BackendNotAvailable
    |   +-- BackendConnectionLost
    +-- VisionError
    |   +-- TemplateNotFound
    |   +-- MatchTimeout
    |   +-- OcrError
    +-- NavigationError
    |   +-- GraphValidationError
    |   +-- NoPathFound
    |   +-- UnknownVertex
    |   +-- CurrentVertexUnknown
    |   +-- EdgeExecutionFailed
    +-- PluginError          (reserved for Phase 3)
"""

from __future__ import annotations


class BotError(Exception):
    """Root of every error this project raises on purpose.

    Catch this at the top of a worker loop to differentiate "our bug" from
    "the runtime exploded" (KeyboardInterrupt, MemoryError, etc.).
    """


# --------------------------------------------------------------------------- #
# Input backend
# --------------------------------------------------------------------------- #
class InputBackendError(BotError):
    """Anything that goes wrong inside `core.input_backend`.

    Concrete backends (nemu, scrcpy, ADB, ...) must translate their native
    exceptions into a subclass of this so callers stay portable.
    """


class BackendNotAvailable(InputBackendError):
    """The backend cannot be constructed in this environment.

    Triggered when:
      * the underlying DLL / binary is missing or too old,
      * the configured emulator path is invalid,
      * MuMuPlayerGlobal is detected (IPC unsupported).

    Not retryable. Surfacing this means the user must fix configuration.
    """


class BackendConnectionLost(InputBackendError):
    """A previously working backend dropped its connection.

    Triggered when:
      * the emulator was closed mid-run,
      * an IPC call returns a hard error after the backend had connected,
      * automatic reconnect attempts exhausted their retry budget.

    May be retryable at a higher level (operator restarts the emulator).
    """


# --------------------------------------------------------------------------- #
# Vision
# --------------------------------------------------------------------------- #
class VisionError(BotError):
    """Anything that goes wrong inside `core.vision`."""


class TemplateNotFound(VisionError):
    """A template image referenced by `Button.template` does not exist on disk.

    Triggered by `TemplateRepository.get` when the resolved path is missing or
    unreadable. Typically a developer error (typo, forgot to commit the PNG).
    """


class MatchTimeout(VisionError):
    """A `wait_for(button, timeout=...)` call expired without seeing the button.

    Not necessarily fatal: the caller may decide to retry, fall back, or escalate.
    """


class OcrError(VisionError):
    """The OCR engine refused or failed a recognition call.

    Triggered when PaddleOCR raises, returns no result on a non-empty crop, or
    the input array has an unsupported shape/dtype.
    """


# --------------------------------------------------------------------------- #
# Navigation (Phase 2)
# --------------------------------------------------------------------------- #
class NavigationError(BotError):
    """Anything that goes wrong inside `core.navigation`."""


class GraphValidationError(NavigationError):
    """A graph failed structural validation (dangling edges, dup vertex, ...).

    Raised by `GameGraph.validate(strict=True)` and by `GraphAssembler.assemble`
    when its inputs are internally inconsistent (e.g. a subgraph defines a
    vertex that another subgraph already owns).
    """


class NoPathFound(NavigationError):
    """`PathFinder` could not connect source and target.

    Either the destination is unreachable from the source given the current
    constraints (avoid_risky / avoid_tags / max_length_factor), or the
    destination itself is unknown to the graph.
    """


class UnknownVertex(NavigationError):
    """A vertex id was referenced but does not exist in the graph.

    Raised by Navigator / PathFinder / GameGraph helpers when the caller hands
    in a typo'd or stale id. Distinct from `NoPathFound` because the cause is
    a missing definition, not topology.
    """


class CurrentVertexUnknown(NavigationError):
    """`ScreenRecognizer` could not identify the current screen.

    Navigation cannot start from "?", so this is fatal for `goto()` unless the
    caller retries after the UI settles.
    """


class EdgeExecutionFailed(NavigationError):
    """An edge's `action` ran but the UI did not arrive at the expected vertex.

    The action did not raise — it was the post-condition (recognizing the
    destination) that failed. Hand to a higher level so it can replan or escalate.
    """


# --------------------------------------------------------------------------- #
# Plugin / scheduler (Phase 3)
# --------------------------------------------------------------------------- #
class PluginError(BotError):
    """Anything that goes wrong inside `core.scheduler` or a `GameplayPlugin`.

    Concrete subclasses below cover the predictable failure modes; ad-hoc
    runtime explosions (`KeyError`, `AttributeError`, etc.) raised inside a
    plugin's `run()` are NOT translated — `PluginWorker` captures them
    verbatim in `last_error` so callers can debug.
    """


class PluginDiscoveryFailed(PluginError):
    """A directory under `plugins/` could not be imported into a plugin class.

    Raised by `PluginRegistry.discover` when a plugin module's import errors
    out, or when its declared class is missing required attributes. Carried
    in `PluginRegistry.failed`, never thrown out — the scheduler keeps going.
    """


class PluginNotRegistered(PluginError):
    """Asked the registry or scheduler for a plugin name that isn't known.

    Typically a typo in config (`enabled_plugins`) or a stale reference after
    a plugin was renamed.
    """


class AccountNotRegistered(PluginError):
    """`Scheduler.start_plugin(...)` called for an account that has no runtime.

    The caller must run `Scheduler.register_account(...)` first.
    """


class PluginRequirementUnmet(PluginError):
    """A plugin's `requires_vertices` includes ids missing from the assembled graph.

    Raised before the worker starts so we never enter `run()` against an
    incomplete graph. Usually means another plugin the dependency relies on
    is not enabled, or main graph forgot a vertex.
    """


class WorkerAlreadyRunning(PluginError):
    """Tried to start a `(account_id, plugin)` whose worker is still alive.

    Defensive guard — duplicated `start_plugin` calls are almost always a
    bug in the caller. Stop first, then start.
    """


# --------------------------------------------------------------------------- #
# Phase 4 additions
# --------------------------------------------------------------------------- #
class AccountBusy(PluginError):
    """Tried to start a second plugin on an account that already has one running.

    Phase 4 enforces "one plugin per account at a time" as the default
    scheduler policy — see CLAUDE.md S5 for the multi-account-readiness
    rationale and S7 for the Navigator concurrency note. Opt out per
    `Scheduler(concurrent_plugins=True)` when you've audited Navigator
    sharing for your use case.
    """


class ThrottleTimeout(BotError):
    """A `Throttle.wait(timeout=...)` budget elapsed before allowance freed up.

    Use sparingly — most callers should let `wait()` block. Surfaced for
    diagnostics when the project's `max_actions_per_minute` is so tight
    that a plugin is starving.
    """


class RecoveryFailed(PluginError):
    """`GameplayPlugin.handle_unexpected_error` could not return to a safe state.

    Raised after `MAX_RECOVERY_ATTEMPTS` attempts of `recover_to_main`
    all failed. Worker takes this as "stop the plugin and notify the
    scheduler" — its status stays ERROR and a stop is signalled.
    """


class ConfigError(BotError):
    """`config/config.yaml` (or the loader) produced an invalid configuration.

    Raised by `core.config.load_config` for: missing required keys,
    invalid types, unknown plugins listed under an account, contradictory
    long-run policy values, etc. Surfaces in `main.py` before any
    backend is constructed so the operator sees the problem early.
    """
