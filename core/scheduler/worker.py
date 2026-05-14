"""
`PluginWorker` — one OS thread that owns one `(account, plugin)` pair.

Lifecycle:

    IDLE ── start() ──> RUNNING ── stop() ──> STOPPED
                          │
                          ├── pause() ──> PAUSED ── resume() ──> RUNNING
                          │
                          └── (exception) ──> ERROR

Threading invariants:
  * `setup`, `run`, `teardown`, `on_pause`, `on_resume` are called from
    *one* thread — the worker's own.
  * `start` / `pause` / `resume` / `stop` are called from outside (main
    thread, scheduler dispatcher, hotkey thread). They are non-blocking
    (well, `stop` blocks up to `timeout` for the worker to drain).
  * Status transitions happen under `self._lock`; concurrent reads of
    `status` are always safe.

Exception handling:
  * `setup` / `run` exceptions land in `last_error` and flip status to
    ERROR. `teardown` runs regardless. A teardown failure is logged and
    overwrites `last_error` with the teardown exception only if `run`
    didn't already set one — we surface the primary cause.
  * `KeyboardInterrupt` inside the worker thread propagates back to the
    Python runtime; the main thread will see it via `Thread.is_alive` =
    False and may want to call `stop()` on its peers.
"""

from __future__ import annotations

import enum
import threading
import time
import traceback
from typing import Optional

from core.exceptions import BotError, WorkerAlreadyRunning
from core.logging_config import get_logger
from core.scheduler.plugin_base import GameplayPlugin, PluginContext

log = get_logger(__name__)


class WorkerStatus(enum.Enum):
    """Lifecycle status of a `PluginWorker`. See module docstring for transitions."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


# Sentinel timeout for the implicit join in __del__ / GC paths.
_GRACEFUL_STOP_TIMEOUT = 10.0


class PluginWorker:
    """Wraps a `GameplayPlugin` in a `threading.Thread` with lifecycle control."""

    def __init__(
        self,
        plugin: GameplayPlugin,
        context: PluginContext,
        *,
        name: Optional[str] = None,
    ) -> None:
        """Construct an IDLE worker. Does not start the thread.

        Args:
            plugin: A constructed plugin instance. The worker owns its
                lifecycle for the duration of one start/stop cycle.
            context: The `PluginContext` to pass into every lifecycle
                hook. Its `_stop_event` / `_pause_event` are bound to
                this worker.
            name: Optional thread name. Defaults to
                ``"PluginWorker[{account}/{plugin}]"``.
        """
        self._plugin = plugin
        self._context = context
        self._thread_name = (
            name
            or f"PluginWorker[{context.account_id}/{plugin.name}]"
        )

        # Use the context's events so the plugin can observe them via
        # ctx.should_stop()/should_pause(). The worker also owns them
        # for setting/clearing.
        self._stop_event = context._stop_event
        self._pause_event = context._pause_event

        self._lock = threading.RLock()
        self._status = WorkerStatus.IDLE
        self._last_error: Optional[BaseException] = None
        self._thread: Optional[threading.Thread] = None
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Introspection (thread-safe reads)
    # ------------------------------------------------------------------ #
    @property
    def plugin(self) -> GameplayPlugin:
        return self._plugin

    @property
    def context(self) -> PluginContext:
        return self._context

    @property
    def status(self) -> WorkerStatus:
        with self._lock:
            return self._status

    @property
    def last_error(self) -> Optional[BaseException]:
        with self._lock:
            return self._last_error

    @property
    def started_at(self) -> Optional[float]:
        return self._started_at

    @property
    def finished_at(self) -> Optional[float]:
        return self._finished_at

    def is_alive(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    # ------------------------------------------------------------------ #
    # Control
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Spin up the worker thread. Idempotent only across STOPPED/ERROR cycles.

        Raises:
            WorkerAlreadyRunning: status is RUNNING or PAUSED, or the
                underlying thread is still alive.
        """
        with self._lock:
            if self._status in (WorkerStatus.RUNNING, WorkerStatus.PAUSED):
                raise WorkerAlreadyRunning(
                    f"worker {self._thread_name} is already {self._status.value}"
                )
            if self._thread is not None and self._thread.is_alive():
                raise WorkerAlreadyRunning(
                    f"worker {self._thread_name} thread is still alive"
                )

            # Reset events + bookkeeping for a fresh run.
            self._stop_event.clear()
            self._pause_event.clear()
            self._last_error = None
            self._status = WorkerStatus.RUNNING
            self._started_at = time.monotonic()
            self._finished_at = None

            self._thread = threading.Thread(
                target=self._run_lifecycle,
                name=self._thread_name,
                daemon=True,
            )
            self._thread.start()

    def pause(self) -> None:
        """Request the plugin to pause.

        Sets the pause event and fires `plugin.on_pause(ctx)` on the
        *worker* thread asynchronously — calling thread returns immediately.
        Plugins notice pause via `ctx.should_pause()` and typically
        idle-loop via `ctx.wait_until_resumed()`.
        """
        with self._lock:
            if self._status not in (WorkerStatus.RUNNING, WorkerStatus.PAUSED):
                log.debug(
                    "%s: pause requested while %s; ignored",
                    self._thread_name, self._status.value,
                )
                return
            already = self._pause_event.is_set()
            self._pause_event.set()
            self._status = WorkerStatus.PAUSED
        if not already:
            try:
                self._plugin.on_pause(self._context)
            except Exception:  # noqa: BLE001
                log.exception(
                    "%s: on_pause hook raised; pause still active",
                    self._thread_name,
                )

    def resume(self) -> None:
        """Clear the pause request. Fires `plugin.on_resume(ctx)` once.

        Calling resume on a non-paused worker is a no-op.
        """
        with self._lock:
            if not self._pause_event.is_set():
                return
            self._pause_event.clear()
            # Only flip to RUNNING if we're actually mid-flight; ERROR /
            # STOPPED stay where they are.
            if self._status == WorkerStatus.PAUSED:
                self._status = WorkerStatus.RUNNING
        try:
            self._plugin.on_resume(self._context)
        except Exception:  # noqa: BLE001
            log.exception(
                "%s: on_resume hook raised; resume still applied",
                self._thread_name,
            )

    def stop(self, timeout: float = _GRACEFUL_STOP_TIMEOUT) -> bool:
        """Signal stop and join the worker thread.

        Args:
            timeout: Max seconds to wait for the thread to drain. If it
                doesn't, returns False and the thread is left alive
                (Python has no safe way to kill a thread). Caller can
                escalate to process exit.

        Returns:
            True if the thread exited within `timeout`. False if it
            outlasted the timeout (still set status to STOPPED so the
            scheduler can move on; the rogue thread is daemonic).
        """
        with self._lock:
            self._stop_event.set()
            # Clear pause too so the plugin's wait_until_resumed unblocks.
            self._pause_event.clear()
            thread = self._thread

        if thread is None:
            with self._lock:
                if self._status not in (WorkerStatus.ERROR,):
                    self._status = WorkerStatus.STOPPED
            return True

        thread.join(timeout=timeout)
        joined = not thread.is_alive()
        with self._lock:
            if joined and self._status not in (WorkerStatus.ERROR,):
                self._status = WorkerStatus.STOPPED
            elif not joined:
                log.warning(
                    "%s: thread did not exit within %.1fs; leaving daemonic",
                    self._thread_name, timeout,
                )
                # Keep current status (likely RUNNING/PAUSED) — caller may
                # decide what to do. We do NOT lie about STOPPED here.
        return joined

    # ------------------------------------------------------------------ #
    # The worker thread body
    # ------------------------------------------------------------------ #
    def _run_lifecycle(self) -> None:
        """Executes `setup -> run -> teardown` in the worker thread."""
        ctx = self._context
        log.info("%s: starting", self._thread_name)
        run_error: Optional[BaseException] = None
        try:
            try:
                self._plugin.setup(ctx)
            except BaseException as exc:  # noqa: BLE001
                run_error = exc
                self._record_error(exc, where="setup")
                return

            try:
                self._plugin.run(ctx)
            except BaseException as exc:  # noqa: BLE001
                run_error = exc
                self._record_error(exc, where="run")
                # Phase 4 recovery: try to bring the UI back to a known
                # safe vertex so the next plugin (or a manual operator)
                # doesn't inherit a stuck modal. Swallow recovery's own
                # exceptions — the original run() error is the primary
                # finding and stays in `last_error`.
                if getattr(self._plugin, "AUTO_RECOVER_ON_UNEXPECTED_ERROR", False):
                    try:
                        recovered = self._plugin.handle_unexpected_error(ctx, exc)
                    except Exception:  # noqa: BLE001
                        log.exception(
                            "%s: handle_unexpected_error itself raised; "
                            "keeping the original run() error as primary",
                            self._thread_name,
                        )
                        recovered = False
                    if recovered:
                        log.info(
                            "%s: post-error recovery returned to safe vertex",
                            self._thread_name,
                        )
                    else:
                        log.warning(
                            "%s: post-error recovery failed; plugin will stay in ERROR",
                            self._thread_name,
                        )
                return

            log.info("%s: run() returned normally", self._thread_name)
        finally:
            try:
                self._plugin.teardown(ctx)
            except BaseException as exc:  # noqa: BLE001
                # Don't clobber a primary error from run().
                if run_error is None:
                    self._record_error(exc, where="teardown")
                else:
                    log.exception(
                        "%s: teardown raised after run error; "
                        "keeping the run() error as primary",
                        self._thread_name,
                    )

            with self._lock:
                self._finished_at = time.monotonic()
                # If we never errored, finalize as STOPPED. The ERROR
                # status was set by _record_error; preserve it.
                if self._status != WorkerStatus.ERROR:
                    self._status = WorkerStatus.STOPPED
                # Always clear pause on exit so a future stop() returns fast.
                self._pause_event.clear()
            log.info("%s: finished (status=%s)",
                     self._thread_name, self._status.value)

    def _record_error(self, exc: BaseException, *, where: str) -> None:
        """Capture an exception raised in a lifecycle hook."""
        with self._lock:
            self._last_error = exc
            self._status = WorkerStatus.ERROR
        if isinstance(exc, BotError):
            log.error(
                "%s: %s raised %s: %s",
                self._thread_name, where, type(exc).__name__, exc,
            )
        else:
            # Non-BotError = either a runtime explosion or a bug; print
            # the full traceback at ERROR level so we can debug.
            log.error(
                "%s: %s raised non-BotError %s: %s\n%s",
                self._thread_name, where, type(exc).__name__, exc,
                "".join(traceback.format_exception(exc)),
            )

    # ------------------------------------------------------------------ #
    # Repr
    # ------------------------------------------------------------------ #
    def __repr__(self) -> str:
        return (
            f"<PluginWorker {self._thread_name} status={self._status.value} "
            f"alive={self.is_alive()}>"
        )
