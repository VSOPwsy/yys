"""
Phase 3 scheduler layer.

Subpackage layout:
  * `plugin_base`  — `GameplayPlugin` ABC + `PluginContext` data class. The
                     contract every gameplay plugin honors.
  * `registry`     — `PluginRegistry`: scan `plugins/`, import, register
                     `GameplayPlugin` subclasses, collect their subgraphs.
  * `worker`       — `PluginWorker`: one OS thread that owns one plugin
                     instance + its `PluginContext`, lifecycle-managed.
  * `scheduler`    — `Scheduler`: per-account dict of workers, command
                     queue, start/stop/pause API.

Public re-exports below let callers do
``from core.scheduler import GameplayPlugin, Scheduler``.
"""

from core.scheduler.plugin_base import GameplayPlugin, PluginContext
from core.scheduler.registry import PluginRegistry
from core.scheduler.scheduler import AccountRuntime, Scheduler
from core.scheduler.worker import PluginWorker, WorkerStatus

__all__ = [
    "AccountRuntime",
    "GameplayPlugin",
    "PluginContext",
    "PluginRegistry",
    "PluginWorker",
    "Scheduler",
    "WorkerStatus",
]
