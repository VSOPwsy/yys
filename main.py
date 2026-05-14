"""
Phase 4 entry point — config-driven multi-account orchestrator.

Boot sequence:
    1. Load ``config/config.yaml`` (path overridable via CLI / env).
    2. Configure logging (per-account log dir).
    3. Discover plugins under ``plugins/`` via `PluginRegistry`.
    4. Build the main graph + collect each account's enabled subgraphs.
    5. For each account in the config:
         a. construct `Throttle` + backend (nemu or fake);
         b. assemble the graph for the account's enabled plugin set;
         c. build the `Navigator` + `CacheManager`;
         d. wrap everything in an `AccountRuntime` and register with the
            scheduler.
    6. Start the scheduler dispatcher + the long-run watchdog +
       hotkey controller.
    7. Submit `start_plugin` per (account, enabled_plugin) — one at a
       time per account, scheduler enforces `concurrent_plugins=False`
       so a misconfigured config still won't race the Navigator.
    8. Wait until all workers finish (or daily-cap or Ctrl+C); shut down
       in reverse order.

Run::

    D:\\anaconda3\\envs\\yys\\python.exe main.py
    D:\\anaconda3\\envs\\yys\\python.exe main.py --config config/custom.yaml

CLAUDE.md S5 multi-account principle is honored throughout — every
state-bearing object (backend / matcher / cache / navigator / throttle)
is per-`account_id`. Adding a second account is a pure additive change
in `config.yaml`.
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import signal
import sys
import threading
from typing import List, Optional

from core.cache.manager import CacheManager
from core.config import (
    AccountConfig,
    AppConfig,
    GlobalConfig,
    load_config,
)
from core.exceptions import BackendNotAvailable, ConfigError
from core.hotkey.controller import HotkeyController
from core.input_backend.base import InputBackend
from core.input_backend.factory import get_input_backend
from core.logging_config import get_logger, setup_logging
from core.navigation import GraphAssembler, Navigator, PathFinder, ScreenRecognizer
from core.scheduler import (
    AccountRuntime,
    PluginRegistry,
    Scheduler,
)
from core.scheduler.longrun import LongRunPolicy
from core.scheduler.throttle import Throttle
from graphs.main import build_main_graph

log = get_logger(__name__)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "--config",
        default=os.environ.get("YYS_CONFIG", "config/config.yaml"),
        help="Path to config.yaml (env var: YYS_CONFIG; default config/config.yaml)",
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("YYS_LOG_LEVEL", "INFO"),
        help="Root log level (DEBUG/INFO/WARNING/ERROR; default INFO)",
    )
    return p.parse_args(argv)


def _make_throttle(account_id: str, g: GlobalConfig) -> Throttle:
    """Build the per-account `Throttle` from the global humanize policy.

    Stored on `AccountRuntime.backend` so every action goes through it.
    Per-account = per-Throttle, so two accounts don't share the rate
    budget (CLAUDE.md S5 multi-account principle).
    """
    return Throttle(
        min_interval=g.humanize.min_action_interval_ms / 1000.0,
        max_actions_per_window=g.humanize.max_actions_per_minute,
        window_seconds=60.0,
        name=account_id,
    )


def _build_backend(
    account_cfg: AccountConfig,
    g: GlobalConfig,
    throttle: Throttle,
) -> InputBackend:
    """Instantiate the configured emulator backend for one account."""
    backend_name = account_cfg.emulator.backend
    if backend_name == "fake":
        # Test / dev mode: bypass real emulator wiring entirely.
        # Lazy import keeps the production path free of test deps.
        from core.input_backend.fake import FakeBackend
        return FakeBackend(
            initial_screen="main_menu",
            account_id=account_cfg.id,
            throttle=throttle,
            jitter_radius=g.humanize.click_jitter_radius,
            post_delay_variance=g.humanize.post_delay_variance,
        )
    # Real nemu backend. `get_input_backend` raises BackendNotAvailable
    # for misconfigured paths; we let it propagate so main.py exits early.
    return get_input_backend(
        account_id=account_cfg.id,
        backend_name=backend_name,
        mumu_folder=account_cfg.emulator.mumu_folder,
        instance_id=account_cfg.emulator.instance_id,
        display_id=account_cfg.emulator.display_id,
        throttle=throttle,
        jitter_radius=g.humanize.click_jitter_radius,
        post_delay_variance=g.humanize.post_delay_variance,
    )


def _build_account_runtime(
    cfg: AccountConfig,
    g: GlobalConfig,
    registry: PluginRegistry,
) -> AccountRuntime:
    """Wire up backend + graph + navigator + cache for one account."""
    enabled = cfg.enabled_plugin_names
    log.info("account %r: enabled plugins = %s", cfg.id, enabled)

    throttle = _make_throttle(cfg.id, g)
    backend = _build_backend(cfg, g, throttle)
    backend.connect()

    asm = GraphAssembler()
    asm.set_main(build_main_graph())
    subgraphs = registry.collect_subgraphs(only=enabled)
    for namespace, subgraph in subgraphs.items():
        asm.add_subgraph(namespace, subgraph)
    graph = asm.assemble(enabled_plugins=set(subgraphs))

    pathfinder = PathFinder(graph)
    recognizer = ScreenRecognizer(matcher=backend.matcher)
    navigator = Navigator(
        backend=backend,
        graph=graph,
        pathfinder=pathfinder,
        recognizer=recognizer,
    )

    # Per-account cache. OCR is constructed lazily on first plugin demand
    # (paddleocr is heavy and may not be installed).
    cache = CacheManager(account_id=cfg.id)

    return AccountRuntime(
        account_id=cfg.id,
        backend=backend,
        graph=graph,
        navigator=navigator,
        matcher=backend.matcher,
        cache=cache,
        ocr=None,
    )


def _print_help(controller: HotkeyController) -> None:
    log.info("hotkeys:")
    for a in controller.list():
        log.info("  %-8s %s", a.hotkey, a.description or "(no description)")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    setup_logging(level=getattr(logging, args.log_level.upper(), logging.INFO))
    log.info("=== Phase 4: %s ===", pathlib.Path(args.config).resolve())

    # 1. Load + validate config (fails early with a clear message).
    try:
        app_cfg = load_config(args.config)
    except ConfigError as e:
        log.error("config error: %s", e)
        return 2

    if not app_cfg.accounts:
        log.error("config has no accounts; nothing to do")
        return 2

    # 2. Discover plugins. Failures are accumulated, not thrown.
    registry = PluginRegistry()
    registry.discover()
    for f in registry.failed:
        log.warning("plugin discovery failure: %s — %s", f.module, f.reason)
    log.info("plugins registered: %s", registry.list())

    sched_policy = app_cfg.global_.scheduler
    scheduler = Scheduler(
        registry,
        graceful_stop_timeout=sched_policy.graceful_stop_timeout_seconds,
        concurrent_plugins=sched_policy.concurrent_plugins,
        inter_plugin_gap=sched_policy.inter_plugin_gap_seconds,
    )
    scheduler.start()

    runtimes: List[AccountRuntime] = []
    controller: Optional[HotkeyController] = None
    longrun: Optional[LongRunPolicy] = None
    daily_cap_event = threading.Event()

    try:
        # 3. Build per-account stacks.
        for acc in app_cfg.accounts:
            try:
                runtime = _build_account_runtime(acc, app_cfg.global_, registry)
            except BackendNotAvailable as e:
                log.error(
                    "account %r: backend unavailable: %s — skipping", acc.id, e
                )
                continue
            scheduler.register_account(runtime)
            runtimes.append(runtime)

        if not runtimes:
            log.error("no account could be initialized; aborting")
            return 3

        # 4. Hotkeys.
        controller = HotkeyController(
            scheduler, backend=app_cfg.global_.hotkeys.backend
        )
        controller.register(
            app_cfg.global_.hotkeys.pause,
            callback=lambda s=scheduler: s.submit(s.toggle_pause_all),
            description="toggle pause for all workers",
        )
        controller.register(
            app_cfg.global_.hotkeys.stop,
            callback=lambda s=scheduler: s.submit(s.stop_all),
            description="stop all workers",
        )
        controller.register(
            app_cfg.global_.hotkeys.exit,
            callback=_make_emergency_exit(scheduler),
            description="emergency exit",
        )
        controller.start()
        _print_help(controller)

        # 5. SIGINT handler (Ctrl+C from the keyboard library can leave threads alive
        # — route it through the scheduler so cleanup is uniform).
        def _on_sigint(signum, frame):  # noqa: ARG001
            log.warning("SIGINT received; stopping all workers")
            scheduler.submit(scheduler.stop_all)
        signal.signal(signal.SIGINT, _on_sigint)

        # 6. Long-run policy: rest cycles + daily cap.
        longrun = LongRunPolicy(
            scheduler,
            daily_max_runtime=sched_policy.daily_max_runtime_minutes * 60.0,
            rest_every=sched_policy.rest_every_minutes * 60.0,
            rest_duration=sched_policy.rest_duration_minutes * 60.0,
            on_daily_cap_reached=daily_cap_event.set,
        )
        longrun.start()

        # 7. Start the enabled plugins per account.
        for acc in app_cfg.accounts:
            for plugin_name in acc.enabled_plugin_names:
                try:
                    scheduler.start_plugin(plugin_name, acc.id)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "failed to start (%s, %s) — continuing",
                        acc.id, plugin_name,
                    )

        # 8. Block until workers are done OR the daily cap fired.
        log.info("running; hotkeys are active")
        try:
            while True:
                if daily_cap_event.is_set():
                    log.warning("daily cap reached; shutting down")
                    break
                if scheduler.wait_for_idle(timeout=1.0):
                    break
        except KeyboardInterrupt:
            log.warning("KeyboardInterrupt in main loop; stopping workers")
            scheduler.stop_all()

        log.info("final status: %s", scheduler.list_status())

    finally:
        # Shutdown order: longrun watchdog (so it doesn't race
        # pause_all during our shutdown), hotkeys, scheduler, backends.
        if longrun is not None:
            try:
                longrun.stop()
            except Exception:  # noqa: BLE001
                log.exception("longrun.stop() raised")
        if controller is not None:
            try:
                controller.stop()
            except Exception:  # noqa: BLE001
                log.exception("hotkey controller.stop() raised")
        try:
            scheduler.shutdown()
        except Exception:  # noqa: BLE001
            log.exception("scheduler.shutdown() raised")
        for runtime in runtimes:
            try:
                runtime.backend.disconnect()
            except Exception:  # noqa: BLE001
                log.exception(
                    "backend disconnect for %r raised", runtime.account_id
                )

    log.info("=== shutdown complete ===")
    return 0


def _make_emergency_exit(scheduler: Scheduler):
    """F12 callback: best-effort stop, then os._exit(2).

    Bypasses atexit / try-finally so a wedged worker can't keep the
    process alive (Python threads can't be force-killed, but the
    process can).
    """
    def _exit() -> None:
        log.warning("emergency exit requested")
        try:
            scheduler.stop_all(timeout=2.0)
        except Exception:  # noqa: BLE001
            log.exception("emergency stop_all raised; exiting anyway")
        os._exit(2)
    return _exit


if __name__ == "__main__":
    sys.exit(main())
