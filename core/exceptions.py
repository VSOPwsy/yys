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
    +-- NavigationError      (reserved for Phase 2)
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
    """Anything that goes wrong inside `core.navigation`.

    Reserved for Phase 2. Subclasses will cover "no path between A and B",
    "current vertex unknown", "edge action did not produce expected vertex",
    etc.
    """


# --------------------------------------------------------------------------- #
# Plugin / scheduler (Phase 3)
# --------------------------------------------------------------------------- #
class PluginError(BotError):
    """Anything that goes wrong inside `core.scheduler` or a `GameplayPlugin`.

    Reserved for Phase 3. Subclasses will cover "plugin import failed",
    "plugin worker raised", "command queue closed", etc.
    """
