"""
Phase 3 entry point — wires registry + scheduler + hotkeys, runs the demo plugin.

Runtime sequence:
    1. Configure logging (per-account log dir).
    2. Load a tiny inline config (single account, single plugin enabled).
    3. Discover plugins under `plugins/` via `PluginRegistry`.
    4. Build main graph + collect enabled subgraphs + assemble.
    5. Per account, build backend / matcher / cache / navigator and
       wrap them in an `AccountRuntime`.
    6. Start `Scheduler`, register the account, start the enabled plugins.
    7. Start `HotkeyController` with F9 / F10 / F12 defaults.
    8. Wait for workers to idle (or Ctrl+C) and clean up.

To run against a real emulator, swap `FakeBackend(...)` for
`get_input_backend(account_id, "nemu", mumu_folder="...")`. The demo
plugin will still work but won't actually move screens because its
fake actions write to `FakeBackend.current_screen`. A real plugin would
do real clicks via its own actions.

Run::

    D:\\anaconda3\\envs\\yys\\python.exe main.py
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from dataclasses import dataclass
from typing import List

from core.cache.manager import CacheManager
from core.hotkey.controller import HotkeyController
from core.input_backend.fake import FakeBackend
from core.logging_config import get_logger, setup_logging
from core.navigation import GraphAssembler, Navigator, PathFinder, ScreenRecognizer
from core.scheduler import (
    AccountRuntime,
    PluginRegistry,
    Scheduler,
)
from graphs._demo import build_main_graph

log = get_logger(__name__)


@dataclass
class AccountConfig:
    """One account's startup config. Real config will be YAML; for now hardcoded."""

    account_id: str
    enabled_plugins: List[str]
    initial_screen: str = "main_menu"


def _load_config() -> List[AccountConfig]:
    """Return the (hardcoded) Phase 3 demo config.

    Phase 4 will switch this to a YAML loader. The list-of-accounts shape
    is already correct so future expansion is additive.
    """
    return [
        AccountConfig(
            account_id="demo",
            enabled_plugins=["_demo"],
            initial_screen="main_menu",
        ),
    ]


def _build_account_runtime(
    cfg: AccountConfig,
    registry: PluginRegistry,
) -> AccountRuntime:
    """Build the per-account stack: backend, graph, navigator, cache."""
    # 1. Backend (FakeBackend in the demo; real apps use get_input_backend).
    backend = FakeBackend(
        initial_screen=cfg.initial_screen,
        account_id=cfg.account_id,
    )
    backend.connect()

    # 2. Assemble main + enabled plugin subgraphs.
    asm = GraphAssembler()
    asm.set_main(build_main_graph())
    subgraphs = registry.collect_subgraphs(only=cfg.enabled_plugins)
    for namespace, subgraph in subgraphs.items():
        asm.add_subgraph(namespace, subgraph)
    graph = asm.assemble(enabled_plugins=set(subgraphs))

    # 3. Navigator + supporting pieces.
    pathfinder = PathFinder(graph)
    recognizer = ScreenRecognizer(matcher=backend.matcher)
    navigator = Navigator(
        backend=backend,
        graph=graph,
        pathfinder=pathfinder,
        recognizer=recognizer,
    )

    # 4. Per-account cache. OCR stays None until somebody asks for it.
    cache = CacheManager(account_id=cfg.account_id)

    return AccountRuntime(
        account_id=cfg.account_id,
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


def main() -> int:
    setup_logging(level=logging.INFO)
    log.info("=== Phase 3 demo: scheduler + hotkeys ===")

    # 1. Discover plugins.
    registry = PluginRegistry()
    registry.discover()
    for f in registry.failed:
        log.warning("plugin discovery failure: %s — %s", f.module, f.reason)
    log.info("plugins registered: %s", registry.list())

    # 2. Load config + build per-account runtimes.
    configs = _load_config()
    scheduler = Scheduler(registry)
    scheduler.start()

    runtimes: List[AccountRuntime] = []
    try:
        for cfg in configs:
            runtime = _build_account_runtime(cfg, registry)
            scheduler.register_account(runtime)
            runtimes.append(runtime)

        # 3. Hotkeys.
        controller = HotkeyController(scheduler)
        controller.register_defaults()
        controller.start()
        _print_help(controller)

        # 4. Install a SIGINT handler that stops everything cleanly.
        # Without this, Ctrl+C from the keyboard library can leave threads alive.
        def _on_sigint(signum, frame):  # noqa: ARG001
            log.warning("SIGINT received; stopping all workers")
            scheduler.submit(scheduler.stop_all)
        signal.signal(signal.SIGINT, _on_sigint)

        # 5. Start the configured plugins per account.
        for cfg in configs:
            for plugin_name in cfg.enabled_plugins:
                try:
                    scheduler.start_plugin(plugin_name, cfg.account_id)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "failed to start (%s, %s) — continuing",
                        cfg.account_id, plugin_name,
                    )

        # 6. Wait for everyone to finish. F12 will exit via os._exit.
        log.info("waiting for workers; F9 = pause/resume, F10 = stop all, F12 = exit")
        try:
            while True:
                if scheduler.wait_for_idle(timeout=1.0):
                    break
        except KeyboardInterrupt:
            log.warning("KeyboardInterrupt in main loop; stopping workers")
            scheduler.stop_all()

        log.info("status: %s", scheduler.list_status())

    finally:
        try:
            scheduler.shutdown()
        except Exception:  # noqa: BLE001
            log.exception("scheduler shutdown raised")
        for runtime in runtimes:
            try:
                runtime.backend.disconnect()
            except Exception:  # noqa: BLE001
                log.exception("backend disconnect for %r raised", runtime.account_id)

    log.info("=== shutdown complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
