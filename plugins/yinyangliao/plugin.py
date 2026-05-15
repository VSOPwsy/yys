from __future__ import annotations

from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin, PluginContext


class YinyangliaoPlugin(GameplayPlugin):
    """阴阳寮 plugin — scaffold only, no gameplay defined yet."""

    name = "yinyangliao"
    display_name = "阴阳寮"

    # The scheduler validates these exist in the assembled graph before
    # starting the worker. `yinyangliao.home` is contributed by this
    # plugin's own subgraph; `tingyuan` is the root home screen.
    requires_vertices = [
        "tingyuan",
        "yinyangliao.home",
    ]

    # Where to land if `run()` raises. Inherited default is "main_menu"
    # which doesn't exist in this codebase yet; override to "tingyuan".
    SAFE_VERTEX = "tingyuan"

    @classmethod
    def build_subgraph(cls) -> GameGraph:
        from plugins.yinyangliao.graph import build_subgraph as _build
        return _build()

    # ------------------------------------------------------------------ #
    # Lifecycle — placeholders. Replace `run()` with real gameplay.
    # ------------------------------------------------------------------ #
    def setup(self, ctx: PluginContext) -> None:
        ctx.logger.info("YinyangliaoPlugin: scaffold setup (no-op)")

    def run(self, ctx: PluginContext) -> None:
        ctx.logger.info(
            "YinyangliaoPlugin: no gameplay implemented yet; returning."
            " Replace plugin.run() to add real logic."
        )

    def teardown(self, ctx: PluginContext) -> None:
        ctx.logger.info("YinyangliaoPlugin: scaffold teardown (no-op)")
