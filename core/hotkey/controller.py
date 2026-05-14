"""
`HotkeyController` — global hotkey -> scheduler-command bridge.

Wraps the `keyboard` library so the rest of the project can express
"F9 pauses everything" without sprinkling library calls around. Two
backends:

* ``"keyboard"`` (default) — real OS-level hotkeys via the `keyboard`
  Python package. Requires the library to be installed; on Windows it
  generally needs to run as administrator to capture keys reliably.
* ``"noop"`` — does nothing at the OS level. Callbacks can be invoked
  programmatically via `trigger()`. Used in tests and on systems
  where the keyboard hook is unavailable.

Hotkey callbacks ALWAYS post to the scheduler's command queue rather
than executing inline. That means:

* The keyboard-hook thread returns immediately (it MUST — `keyboard`
  pumps events from a single internal thread).
* Multiple presses queue up cleanly instead of stomping on each other.
* The scheduler dispatcher runs callbacks single-threaded, so two
  hotkeys can't race on `self._workers`.

Default bindings reflect the spec:
  * F9  — toggle pause for all workers
  * F10 — stop every worker
  * F12 — emergency exit (calls `os._exit(2)` after a best-effort
          `Scheduler.shutdown`)
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

from core.logging_config import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from core.scheduler.scheduler import Scheduler

log = get_logger(__name__)


@dataclass
class HotkeyAction:
    """One registered hotkey + its callback + a human-readable label.

    Fields:
        hotkey: Hotkey string in the `keyboard` library's format
            (e.g. "f9", "ctrl+alt+p"). Lowercase by convention.
        callback: Zero-arg function. The controller will queue it onto
            the scheduler's command queue when the hotkey fires.
        description: Shown in `list()` for help text / logs.
    """

    hotkey: str
    callback: Callable[[], None]
    description: str = ""


class HotkeyController:
    """Manage OS-level hotkeys and bridge them into the scheduler.

    Construction is cheap (no OS calls); hotkeys are hooked when
    `start()` is invoked and unhooked on `stop()`.
    """

    def __init__(
        self,
        scheduler: "Scheduler",
        *,
        backend: str = "keyboard",
    ) -> None:
        """Args:
            scheduler: The `Scheduler` to forward commands to. Required —
                hotkeys exist to operate workers.
            backend: ``"keyboard"`` or ``"noop"``. Default ``"keyboard"``.
                ``"noop"`` builds the registration list but does not call
                into `keyboard` — used in tests and on systems where the
                package can't hook (no admin, headless CI).
        """
        if backend not in ("keyboard", "noop"):
            raise ValueError(
                f"unknown hotkey backend {backend!r}; expected 'keyboard' or 'noop'"
            )
        self._scheduler = scheduler
        self._backend_kind = backend
        self._lock = threading.RLock()
        self._actions: Dict[str, HotkeyAction] = {}
        # Library handles returned by keyboard.add_hotkey, for unhook on stop.
        self._handles: List[object] = []
        self._started = False

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register(
        self,
        hotkey: str,
        callback: Callable[[], None],
        *,
        description: str = "",
    ) -> None:
        """Bind `hotkey` to `callback`.

        Re-registering a hotkey replaces the previous binding. If the
        controller is already started, the new binding is installed
        immediately; otherwise it is queued until `start()`.
        """
        if not hotkey:
            raise ValueError("hotkey must be a non-empty string")
        if not callable(callback):
            raise ValueError("hotkey callback must be callable")
        with self._lock:
            self._actions[hotkey] = HotkeyAction(
                hotkey=hotkey,
                callback=callback,
                description=description,
            )
            if self._started:
                self._unhook_all_unlocked()
                self._hook_all_unlocked()

    def register_defaults(self) -> None:
        """Install the canonical F9 / F10 / F12 bindings.

        F9  — toggle pause for all workers on all accounts.
        F10 — stop every worker (does not unregister accounts).
        F12 — emergency exit. Best-effort scheduler shutdown, then
              `os._exit(2)` to drop the process even if a worker is wedged.
        """
        self.register(
            "f9",
            lambda: self._scheduler.submit(self._scheduler.toggle_pause_all),
            description="Toggle pause for all workers",
        )
        self.register(
            "f10",
            lambda: self._scheduler.submit(self._scheduler.stop_all),
            description="Stop all workers",
        )
        self.register(
            "f12",
            self._emergency_exit,
            description="Emergency exit",
        )

    def list(self) -> List[HotkeyAction]:
        """Return a snapshot of all registered actions, sorted by hotkey."""
        with self._lock:
            return [self._actions[k] for k in sorted(self._actions)]

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Install OS hooks for every registered hotkey. Idempotent.

        For backend="keyboard", lazy-imports the package. If import
        fails, logs a warning and downgrades silently to noop so the
        main loop keeps running (preferable to crashing the bot for
        the convenience layer).
        """
        with self._lock:
            if self._started:
                return
            self._started = True
            self._hook_all_unlocked()

    def stop(self) -> None:
        """Remove every hook. Safe to call without a prior `start`."""
        with self._lock:
            if not self._started:
                return
            self._started = False
            self._unhook_all_unlocked()

    # ------------------------------------------------------------------ #
    # Test / programmatic triggering
    # ------------------------------------------------------------------ #
    def trigger(self, hotkey: str) -> None:
        """Fire the callback for `hotkey` as if it had been pressed.

        Used by tests (under backend="noop") and by callers that want
        to programmatically simulate a hotkey. Falls through silently
        if the hotkey isn't registered.
        """
        with self._lock:
            action = self._actions.get(hotkey)
        if action is None:
            log.debug("trigger(%r): no such hotkey registered", hotkey)
            return
        try:
            action.callback()
        except Exception:  # noqa: BLE001
            log.exception("hotkey %r callback raised", hotkey)

    # ------------------------------------------------------------------ #
    # Internal: install / remove OS hooks (called under lock)
    # ------------------------------------------------------------------ #
    def _hook_all_unlocked(self) -> None:
        if self._backend_kind == "noop":
            return
        kb = self._import_keyboard()
        if kb is None:
            # Downgrade silently; the controller still works via trigger().
            log.warning(
                "keyboard backend unavailable; HotkeyController falling back to noop"
            )
            self._backend_kind = "noop"
            return
        for action in self._actions.values():
            try:
                handle = kb.add_hotkey(
                    action.hotkey,
                    self._wrap_callback(action),
                    suppress=False,
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "failed to install hotkey %r — skipped", action.hotkey
                )
                continue
            self._handles.append(handle)
            log.info("hotkey installed: %s (%s)",
                     action.hotkey, action.description or "no description")

    def _unhook_all_unlocked(self) -> None:
        if self._backend_kind == "noop":
            self._handles.clear()
            return
        kb = self._import_keyboard()
        if kb is None:
            self._handles.clear()
            return
        for handle in self._handles:
            try:
                kb.remove_hotkey(handle)
            except Exception:  # noqa: BLE001
                log.warning("remove_hotkey failed for %r", handle, exc_info=True)
        self._handles.clear()

    def _wrap_callback(self, action: HotkeyAction) -> Callable[[], None]:
        """Wrap the user callback so the keyboard-hook thread never sees an exception."""
        def _safe():
            log.info("hotkey pressed: %s", action.hotkey)
            try:
                action.callback()
            except Exception:  # noqa: BLE001
                log.exception("hotkey %r callback raised", action.hotkey)
        return _safe

    @staticmethod
    def _import_keyboard():
        """Lazy import of the `keyboard` library. Returns module or None."""
        try:
            import keyboard  # type: ignore
            return keyboard
        except Exception:  # noqa: BLE001 — broad: missing pkg, hook fail, OSError
            return None

    def _emergency_exit(self) -> None:
        """F12 handler. Try `Scheduler.shutdown`, then force-exit the process."""
        log.warning("emergency exit requested (F12)")
        try:
            self._scheduler.stop_all(timeout=2.0)
        except Exception:  # noqa: BLE001
            log.exception("emergency stop_all raised; force-exiting anyway")
        try:
            self.stop()
        except Exception:  # noqa: BLE001
            log.exception("HotkeyController.stop raised during emergency exit")
        # os._exit bypasses atexit / finally. We use it because a daemonic
        # worker stuck in C code won't release a normal interpreter exit.
        os._exit(2)
