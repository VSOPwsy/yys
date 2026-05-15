from __future__ import annotations

from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin, PluginContext


class TansuoPlugin(GameplayPlugin):
    """探索 plugin — scaffold only, no gameplay defined yet."""

    name = "tansuo"
    display_name = "探索"

    # The scheduler validates these exist in the assembled graph before
    # starting the worker. `tansuo.home` is contributed by this
    # plugin's own subgraph; `tingyuan` is the root home screen.
    requires_vertices = [
        "tingyuan",
        "tansuo.home",
    ]

    # Where to land if `run()` raises. Inherited default is "main_menu"
    # which doesn't exist in this codebase yet; override to "tingyuan".
    SAFE_VERTEX = "tingyuan"

    @classmethod
    def build_subgraph(cls) -> GameGraph:
        from plugins.tansuo.graph import build_subgraph as _build
        return _build()

    # ------------------------------------------------------------------ #
    # Lifecycle — placeholders. Replace `run()` with real gameplay.
    # ------------------------------------------------------------------ #
    def setup(self, ctx: PluginContext) -> None:
        ctx.logger.info("TansuoPlugin: scaffold setup (no-op)")

    def run(self, ctx: PluginContext) -> None:
        ctx.logger.info(
            "TansuoPlugin: no gameplay implemented yet; returning."
            " Replace plugin.run() to add real logic."
        )

    def teardown(self, ctx: PluginContext) -> None:
        ctx.logger.info("TansuoPlugin: scaffold teardown (no-op)")
