from __future__ import annotations

from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin, PluginContext


class ShangdianPlugin(GameplayPlugin):
    name = "shangdian"
    display_name = "商店"

    requires_vertices = [
        "tingyuan",
    ]

    SAFE_VERTEX = "tingyuan"

    @classmethod
    def build_subgraph(cls) -> GameGraph:
        from plugins.shangdian.graph import build_subgraph as _build
        return _build()

    # ------------------------------------------------------------------ #
    # Lifecycle — placeholders. Replace `run()` with real gameplay.
    # ------------------------------------------------------------------ #
    def setup(self, ctx: PluginContext) -> None:
        ctx.logger.info("ShangdianPlugin: scaffold setup (no-op)")

    def run(self, ctx: PluginContext) -> None:
        ctx.logger.info(
            "ShangdianPlugin: no gameplay implemented yet; returning."
            " Replace plugin.run() to add real logic."
        )

    def teardown(self, ctx: PluginContext) -> None:
        ctx.logger.info("ShangdianPlugin: scaffold teardown (no-op)")
