"""
`PluginRegistry` — discover and register `GameplayPlugin` subclasses.

Discovery rules:
  * Scan immediate subdirectories of `plugins/` (default), or of a
    user-supplied directory.
  * Skip `__pycache__`, dotfiles, and any directory that is not a Python
    package (no `__init__.py`).
  * For each surviving subdir, `importlib.import_module("plugins.<name>")`.
  * Walk the imported module's attributes; any non-abstract subclass of
    `GameplayPlugin` is registered under its `name` class attribute.

Failure handling: import errors, bad class attributes, duplicate names
are all caught and accumulated into `self.failed`. We never raise out
of `discover()` — a broken plugin must not take the whole bot down.

Subgraph collection: `collect_subgraphs()` calls `build_subgraph()` on
every registered plugin and returns a `{namespace: GameGraph}` dict.
Failures during subgraph construction also land in `self.failed` and
the offending plugin is silently dropped from the result.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Type

from core.exceptions import PluginDiscoveryFailed, PluginNotRegistered
from core.logging_config import get_logger
from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin

log = get_logger(__name__)


@dataclass
class PluginFailure:
    """One record in `PluginRegistry.failed`.

    Attributes:
        module: Dotted module name we tried to load (e.g. "plugins.daily").
        reason: Short human-readable description of what went wrong.
        error: The original exception, preserved for debugging.
    """

    module: str
    reason: str
    error: BaseException


class PluginRegistry:
    """Tracks discovered `GameplayPlugin` classes by `name`.

    Multi-instance safe: the registry only stores *classes*, not
    instances, so it can be shared across multiple `Scheduler` /
    account configurations. Instances are created per-worker by
    the scheduler.
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, Type[GameplayPlugin]] = {}
        self._failed: List[PluginFailure] = []

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def discover(
        self,
        plugins_package: str = "plugins",
        *,
        skip: Optional[Iterable[str]] = None,
    ) -> List[Type[GameplayPlugin]]:
        """Import every package under `plugins_package` and register classes.

        Args:
            plugins_package: Dotted name of the parent package. Default
                ``"plugins"``. Used to construct child module names like
                ``"plugins.daily_quest"``.
            skip: Optional iterable of plugin module names (final segment
                only) to ignore.

        Returns:
            The list of plugin classes that were newly registered by this
            call (excludes ones already registered).

        Note:
            Never raises. Failures end up in `self.failed`.
        """
        skip_set = set(skip or ())
        newly_registered: List[Type[GameplayPlugin]] = []

        # Resolve the package to its filesystem path so we can iterate it.
        try:
            parent = importlib.import_module(plugins_package)
        except Exception as exc:
            self._failed.append(
                PluginFailure(
                    module=plugins_package,
                    reason=f"could not import parent package: {exc}",
                    error=exc,
                )
            )
            return newly_registered

        parent_paths = getattr(parent, "__path__", None)
        if not parent_paths:
            log.warning(
                "plugin package %r has no __path__; discovery skipped",
                plugins_package,
            )
            return newly_registered

        for module_info in pkgutil.iter_modules(parent_paths):
            short = module_info.name
            if short.startswith(".") or short.startswith("__"):
                continue
            if short in skip_set:
                log.info("plugin %r skipped by config", short)
                continue
            full = f"{plugins_package}.{short}"
            try:
                module = importlib.import_module(full)
            except Exception as exc:
                log.warning("plugin %r failed to import: %s", full, exc)
                self._failed.append(
                    PluginFailure(
                        module=full,
                        reason=f"ImportError: {exc}",
                        error=exc,
                    )
                )
                continue

            registered_here = self._register_from_module(module, full)
            newly_registered.extend(registered_here)

        log.info(
            "plugin discovery complete: %d registered, %d failed",
            len(self._plugins),
            len(self._failed),
        )
        return newly_registered

    def _register_from_module(
        self,
        module,
        module_name: str,
    ) -> List[Type[GameplayPlugin]]:
        """Find GameplayPlugin subclasses in `module` and register them."""
        registered: List[Type[GameplayPlugin]] = []
        for _, attr in inspect.getmembers(module):
            if not inspect.isclass(attr):
                continue
            if attr is GameplayPlugin:
                continue
            if not issubclass(attr, GameplayPlugin):
                continue
            # Only register classes *declared* in this module (or in a
            # submodule of it). Re-exports of another plugin's class would
            # otherwise register twice.
            if not (attr.__module__ == module_name
                    or attr.__module__.startswith(module_name + ".")):
                continue
            if inspect.isabstract(attr):
                continue
            try:
                self.register(attr)
                registered.append(attr)
            except Exception as exc:
                log.warning(
                    "plugin class %s.%s failed to register: %s",
                    module_name, attr.__name__, exc,
                )
                self._failed.append(
                    PluginFailure(
                        module=f"{module_name}.{attr.__name__}",
                        reason=str(exc),
                        error=exc,
                    )
                )
        return registered

    # ------------------------------------------------------------------ #
    # Manual registration / lookup
    # ------------------------------------------------------------------ #
    def register(self, plugin_cls: Type[GameplayPlugin]) -> None:
        """Register `plugin_cls` under its `name` attribute.

        Raises:
            PluginDiscoveryFailed: `name` empty / contains '.' / collides.
        """
        if not inspect.isclass(plugin_cls) or not issubclass(
            plugin_cls, GameplayPlugin
        ):
            raise PluginDiscoveryFailed(
                f"{plugin_cls!r} is not a GameplayPlugin subclass"
            )
        name = getattr(plugin_cls, "name", "") or ""
        if not name:
            raise PluginDiscoveryFailed(
                f"{plugin_cls.__name__}.name is empty; cannot register"
            )
        if "." in name:
            raise PluginDiscoveryFailed(
                f"{plugin_cls.__name__}.name ({name!r}) contains '.'; "
                f"plugin names are graph namespaces and must be dot-free"
            )
        existing = self._plugins.get(name)
        if existing is not None and existing is not plugin_cls:
            raise PluginDiscoveryFailed(
                f"plugin name {name!r} collides: "
                f"{existing.__module__}.{existing.__name__} vs "
                f"{plugin_cls.__module__}.{plugin_cls.__name__}"
            )
        self._plugins[name] = plugin_cls
        log.info(
            "registered plugin %r (%s.%s)",
            name, plugin_cls.__module__, plugin_cls.__name__,
        )

    def get(self, name: str) -> Type[GameplayPlugin]:
        """Return the class registered under `name`.

        Raises:
            PluginNotRegistered: no plugin with that name.
        """
        try:
            return self._plugins[name]
        except KeyError as e:
            raise PluginNotRegistered(
                f"plugin {name!r} not registered "
                f"(have: {sorted(self._plugins)})"
            ) from e

    def list(self) -> List[str]:
        """Sorted list of registered plugin names."""
        return sorted(self._plugins)

    @property
    def failed(self) -> List[PluginFailure]:
        """All discovery / registration failures since the registry was built."""
        return list(self._failed)

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: object) -> bool:
        return name in self._plugins

    def __iter__(self):
        return iter(self._plugins.values())

    # ------------------------------------------------------------------ #
    # Subgraph collection
    # ------------------------------------------------------------------ #
    def collect_subgraphs(
        self,
        *,
        only: Optional[Iterable[str]] = None,
    ) -> Dict[str, GameGraph]:
        """Build every registered plugin's subgraph.

        Args:
            only: Optional iterable of plugin names. If given, only those
                plugins' subgraphs are built; unknown names log warning
                and are skipped.

        Returns:
            ``{plugin_name: GameGraph}`` for the plugins whose
            `build_subgraph()` succeeded. A failure (exception inside the
            classmethod) drops the plugin from the result and adds a
            `PluginFailure` entry; we do NOT raise.
        """
        target_names: List[str]
        if only is None:
            target_names = list(self._plugins.keys())
        else:
            target_names = []
            for n in only:
                if n in self._plugins:
                    target_names.append(n)
                else:
                    log.warning(
                        "collect_subgraphs: plugin %r unknown; skipping", n
                    )

        result: Dict[str, GameGraph] = {}
        for name in target_names:
            cls = self._plugins[name]
            try:
                graph = cls.build_subgraph()
            except Exception as exc:
                log.warning(
                    "plugin %r build_subgraph() raised: %s", name, exc
                )
                self._failed.append(
                    PluginFailure(
                        module=f"{cls.__module__}.{cls.__name__}.build_subgraph",
                        reason=f"build_subgraph raised: {exc}",
                        error=exc,
                    )
                )
                continue
            if not isinstance(graph, GameGraph):
                log.warning(
                    "plugin %r build_subgraph() returned %r, expected GameGraph",
                    name, type(graph).__name__,
                )
                self._failed.append(
                    PluginFailure(
                        module=f"{cls.__module__}.{cls.__name__}.build_subgraph",
                        reason=f"returned non-GameGraph: {type(graph).__name__}",
                        error=TypeError(type(graph).__name__),
                    )
                )
                continue
            result[name] = graph
        return result
