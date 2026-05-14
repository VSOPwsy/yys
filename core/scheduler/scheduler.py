"""
`Scheduler` — multi-account, multi-plugin worker manager.

Conceptual layout::

    Scheduler
    ├── account_id_1 (AccountRuntime: backend, graph, navigator, cache, matcher)
    │   ├── plugin_A → PluginWorker (thread)
    │   └── plugin_B → PluginWorker (thread)
    ├── account_id_2 (AccountRuntime)
    │   └── plugin_A → PluginWorker (thread)
    └── command_queue (queue.Queue) → dispatcher thread

Why the dict-of-dicts shape: even if today we only run one account,
*all* state-bearing objects must be per-`account_id` (CLAUDE.md S5). Adding
account 2 then doesn't touch the scheduler's logic — only adds a key.

Command queue: external callers (hotkeys, CLI) post callables. A
dedicated dispatcher thread drains the queue and invokes them, so the
hotkey thread never blocks on a `worker.stop()` join. Direct method
calls from the main thread (during startup) bypass the queue and
execute synchronously under the same lock.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, TYPE_CHECKING

from core.exceptions import (
    AccountNotRegistered,
    PluginRequirementUnmet,
    WorkerAlreadyRunning,
)
from core.logging_config import get_logger
from core.scheduler.plugin_base import GameplayPlugin, PluginContext, make_logger
from core.scheduler.registry import PluginRegistry
from core.scheduler.worker import PluginWorker, WorkerStatus

if TYPE_CHECKING:  # pragma: no cover
    from core.cache.manager import CacheManager
    from core.input_backend.base import InputBackend
    from core.navigation.graph import GameGraph
    from core.navigation.navigator import Navigator
    from core.vision.ocr import OcrEngine
    from core.vision.template_matcher import TemplateMatcher

log = get_logger(__name__)


# Sentinel posted to the command queue to wake the dispatcher for shutdown.
_SHUTDOWN = object()


@dataclass
class AccountRuntime:
    """Per-account state the Scheduler hands to each worker via `PluginContext`.

    All fields are constructed by `main.py` and registered exactly once
    via `Scheduler.register_account`. The Scheduler does not mutate
    these — it only reads them to wire `PluginContext` instances.

    Fields:
        account_id: Identifier (used as log prefix, cache namespace, etc.).
        backend: Connected `InputBackend` for this account.
        graph: Already-assembled `GameGraph` (main + selected subgraphs).
        navigator: `Navigator` over `graph` using `backend`.
        matcher: `TemplateMatcher` (typically shared via `backend.matcher`).
        cache: Per-account `CacheManager`.
        ocr: Optional shared `OcrEngine` (process-wide singleton).
    """

    account_id: str
    backend: "InputBackend"
    graph: "GameGraph"
    navigator: "Navigator"
    matcher: "TemplateMatcher"
    cache: "CacheManager"
    ocr: Optional["OcrEngine"] = None


class Scheduler:
    """Multi-account, multi-plugin worker manager."""

    def __init__(
        self,
        registry: PluginRegistry,
        *,
        graceful_stop_timeout: float = 10.0,
    ) -> None:
        """Construct a scheduler. The dispatcher thread is NOT started yet.

        Args:
            registry: Already-populated `PluginRegistry`. Scheduler reads
                from it but does not own it; the same registry can drive
                multiple scheduler instances (e.g., for tests).
            graceful_stop_timeout: Seconds to wait for each worker to
                drain on stop. Applied per worker.
        """
        self._registry = registry
        self._graceful_stop_timeout = graceful_stop_timeout

        self._lock = threading.RLock()
        self._accounts: Dict[str, AccountRuntime] = {}
        self._workers: Dict[str, Dict[str, PluginWorker]] = {}

        self._command_queue: "queue.Queue[object]" = queue.Queue()
        self._dispatcher_thread: Optional[threading.Thread] = None
        self._dispatcher_running = False

    # ------------------------------------------------------------------ #
    # Lifecycle of the scheduler itself
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start the command dispatcher thread. Idempotent."""
        with self._lock:
            if self._dispatcher_thread is not None and self._dispatcher_thread.is_alive():
                return
            self._dispatcher_running = True
            self._dispatcher_thread = threading.Thread(
                target=self._dispatch_loop,
                name="Scheduler[dispatcher]",
                daemon=True,
            )
            self._dispatcher_thread.start()

    def shutdown(self, *, stop_timeout: Optional[float] = None) -> None:
        """Stop every worker, drain the queue, join the dispatcher.

        Args:
            stop_timeout: Override the per-worker stop timeout. None =
                use the value passed to `__init__`.
        """
        self.stop_all(timeout=stop_timeout)
        with self._lock:
            self._dispatcher_running = False
        # Wake the dispatcher with the sentinel so it returns promptly.
        self._command_queue.put(_SHUTDOWN)
        t = self._dispatcher_thread
        if t is not None and t.is_alive():
            t.join(timeout=5.0)
        with self._lock:
            self._dispatcher_thread = None

    # ------------------------------------------------------------------ #
    # Account registration
    # ------------------------------------------------------------------ #
    def register_account(self, runtime: AccountRuntime) -> None:
        """Register an account's runtime so plugins can be started on it.

        Re-registering the same `account_id` replaces the previous record;
        any running workers for that account are stopped first to avoid
        them holding references to a stale backend.
        """
        # First, snapshot any workers we need to stop while holding the
        # lock, then drop the lock for the actual stop joins.
        with self._lock:
            preexisting = list(self._workers.get(runtime.account_id, {}).values())
        if preexisting:
            log.warning(
                "re-registering account %r with %d active worker(s) — stopping them",
                runtime.account_id, len(preexisting),
            )
            for w in preexisting:
                w.stop(timeout=self._graceful_stop_timeout)
        with self._lock:
            self._accounts[runtime.account_id] = runtime
            self._workers[runtime.account_id] = {}
            log.info("registered account %r", runtime.account_id)

    def unregister_account(self, account_id: str) -> None:
        """Stop and forget every worker for `account_id`, then drop the runtime."""
        self._stop_account_unlocked(account_id, timeout=self._graceful_stop_timeout)
        with self._lock:
            self._accounts.pop(account_id, None)
            self._workers.pop(account_id, None)

    def registered_accounts(self) -> List[str]:
        """Sorted list of currently registered account ids."""
        with self._lock:
            return sorted(self._accounts)

    # ------------------------------------------------------------------ #
    # Worker control (direct API — thread-safe; or via submit())
    # ------------------------------------------------------------------ #
    def start_plugin(self, plugin_name: str, account_id: str) -> PluginWorker:
        """Build and start a worker for `(account, plugin)`.

        Raises:
            AccountNotRegistered: the account has no `AccountRuntime`.
            PluginNotRegistered: plugin name unknown.
            PluginRequirementUnmet: assembled graph is missing one of
                `plugin.requires_vertices`.
            WorkerAlreadyRunning: a worker for this pair is already alive.
        """
        with self._lock:
            runtime = self._get_account(account_id)
            plugin_cls = self._registry.get(plugin_name)

            existing = self._workers.get(account_id, {}).get(plugin_name)
            if existing is not None and existing.is_alive():
                raise WorkerAlreadyRunning(
                    f"worker for ({account_id!r}, {plugin_name!r}) already alive"
                )

            plugin = plugin_cls()
            missing = [
                v for v in plugin.requires_vertices if not runtime.graph.has_vertex(v)
            ]
            if missing:
                raise PluginRequirementUnmet(
                    f"plugin {plugin_name!r} requires vertices {missing!r} "
                    f"not present in account {account_id!r}'s assembled graph"
                )

            ctx = PluginContext(
                account_id=account_id,
                backend=runtime.backend,
                navigator=runtime.navigator,
                matcher=runtime.matcher,
                ocr=runtime.ocr,
                cache=runtime.cache,
                logger=make_logger(account_id, plugin_name),
            )
            worker = PluginWorker(plugin, ctx)
            self._workers.setdefault(account_id, {})[plugin_name] = worker
            worker.start()
            log.info("started worker (%s, %s)", account_id, plugin_name)
            return worker

    def stop_plugin(
        self,
        plugin_name: str,
        account_id: str,
        *,
        timeout: Optional[float] = None,
    ) -> bool:
        """Stop the worker for `(account, plugin)`.

        Returns True if the worker exited within the timeout (or was not
        running), False if it overran.
        """
        with self._lock:
            worker = self._workers.get(account_id, {}).get(plugin_name)
            if worker is None:
                return True
        # Release the lock for the join — stop() may take seconds.
        return worker.stop(timeout=timeout or self._graceful_stop_timeout)

    def pause_plugin(self, plugin_name: str, account_id: str) -> None:
        worker = self._get_worker_or_none(account_id, plugin_name)
        if worker is not None:
            worker.pause()

    def resume_plugin(self, plugin_name: str, account_id: str) -> None:
        worker = self._get_worker_or_none(account_id, plugin_name)
        if worker is not None:
            worker.resume()

    def start_all(self, account_id: Optional[str] = None) -> List[PluginWorker]:
        """Start every registered plugin on one or all accounts.

        Skips pairs whose worker is already alive (no error). Returns the
        list of newly-started workers.
        """
        with self._lock:
            account_ids = [account_id] if account_id else list(self._accounts)
            plugins = self._registry.list()
        started: List[PluginWorker] = []
        for aid in account_ids:
            for pname in plugins:
                try:
                    started.append(self.start_plugin(pname, aid))
                except WorkerAlreadyRunning:
                    continue
                except Exception:  # noqa: BLE001
                    log.exception("start_all: failed to start (%s, %s)", aid, pname)
        return started

    def stop_all(
        self,
        account_id: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
    ) -> None:
        """Stop every worker on one or all accounts."""
        with self._lock:
            account_ids = [account_id] if account_id else list(self._workers)
        effective_timeout = timeout or self._graceful_stop_timeout
        for aid in account_ids:
            self._stop_account_unlocked(aid, timeout=effective_timeout)

    def pause_all(self, account_id: Optional[str] = None) -> None:
        with self._lock:
            account_ids = [account_id] if account_id else list(self._workers)
            workers = [
                w for aid in account_ids
                for w in self._workers.get(aid, {}).values()
            ]
        for w in workers:
            w.pause()

    def resume_all(self, account_id: Optional[str] = None) -> None:
        with self._lock:
            account_ids = [account_id] if account_id else list(self._workers)
            workers = [
                w for aid in account_ids
                for w in self._workers.get(aid, {}).values()
            ]
        for w in workers:
            w.resume()

    def toggle_pause_all(self, account_id: Optional[str] = None) -> None:
        """If any matching worker is paused, resume all; else pause all."""
        with self._lock:
            account_ids = [account_id] if account_id else list(self._workers)
            workers = [
                w for aid in account_ids
                for w in self._workers.get(aid, {}).values()
            ]
        if any(w.status == WorkerStatus.PAUSED for w in workers):
            for w in workers:
                w.resume()
        else:
            for w in workers:
                if w.status == WorkerStatus.RUNNING:
                    w.pause()

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #
    def list_status(self) -> Dict[str, Dict[str, WorkerStatus]]:
        """Snapshot of worker statuses keyed by `(account_id, plugin_name)`."""
        with self._lock:
            return {
                aid: {pname: w.status for pname, w in plugins.items()}
                for aid, plugins in self._workers.items()
            }

    def get_worker(
        self,
        plugin_name: str,
        account_id: str,
    ) -> Optional[PluginWorker]:
        """Return the worker for `(account, plugin)` or None."""
        with self._lock:
            return self._workers.get(account_id, {}).get(plugin_name)

    def wait_for_idle(self, timeout: Optional[float] = None) -> bool:
        """Block until every worker is in STOPPED/ERROR/IDLE, or timeout.

        Args:
            timeout: Seconds. None = wait forever.

        Returns:
            True if all workers became idle, False on timeout.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                still_running = any(
                    w.is_alive()
                    for plugins in self._workers.values()
                    for w in plugins.values()
                )
            if not still_running:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    # ------------------------------------------------------------------ #
    # Command queue API
    # ------------------------------------------------------------------ #
    def submit(self, command: Callable[[], None]) -> None:
        """Enqueue a callable to be run on the dispatcher thread.

        Designed for hotkey callbacks: post a thunk like
        ``lambda: scheduler.stop_all()`` and return immediately. The
        callable runs single-threaded with the rest of the queue.

        Raises:
            ValueError: `command` is not callable.
        """
        if not callable(command):
            raise ValueError("Scheduler.submit requires a callable")
        self._command_queue.put(command)

    def _dispatch_loop(self) -> None:
        """Drain commands until shutdown."""
        log.info("scheduler dispatcher started")
        while True:
            item = self._command_queue.get()
            if item is _SHUTDOWN:
                if not self._dispatcher_running:
                    break
                # Stray sentinel; ignore.
                continue
            try:
                item()  # type: ignore[operator]
            except Exception:  # noqa: BLE001
                log.exception("scheduler command raised; continuing")
        log.info("scheduler dispatcher stopped")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _get_account(self, account_id: str) -> AccountRuntime:
        runtime = self._accounts.get(account_id)
        if runtime is None:
            raise AccountNotRegistered(
                f"account {account_id!r} is not registered with the scheduler "
                f"(have: {sorted(self._accounts)})"
            )
        return runtime

    def _get_worker_or_none(
        self,
        account_id: str,
        plugin_name: str,
    ) -> Optional[PluginWorker]:
        with self._lock:
            return self._workers.get(account_id, {}).get(plugin_name)

    def _stop_account_unlocked(
        self,
        account_id: str,
        *,
        timeout: float,
    ) -> None:
        """Stop every worker for `account_id`. Acquires `_lock` only for the snapshot."""
        with self._lock:
            workers = list(self._workers.get(account_id, {}).values())
        for w in workers:
            w.stop(timeout=timeout)

    def __repr__(self) -> str:
        with self._lock:
            counts = {aid: len(p) for aid, p in self._workers.items()}
        return f"<Scheduler accounts={counts}>"
