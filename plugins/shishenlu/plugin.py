"""
`ShishenluPlugin` — scaffold plugin for the 式神录 (shikigami records)
screen.

Registers the ``shishenlu.home`` vertex so the graph can navigate to
式神录, but **does not have a gameplay loop yet** — ``run()`` returns
immediately. Add real logic (read shikigami stats, OCR levels,
auto-rank, etc.) by replacing ``run()`` and breaking the steps out into
a ``steps.py`` like ``plugins/daily_reward/``.

To enable in production:
    1. Capture ``templates/shishenlu/shishenlu_anchor.png`` (see
       README §5.2 for the workflow).
    2. Add a ``shishenlu: {enabled: true}`` entry under the relevant
       account's ``plugins:`` block in ``config/config.yaml``.
    3. Until then, the ``tingyuan -> shishenlu.home`` edge declared in
       ``graphs/main.py`` will be dropped as dangling at startup with a
       warning — that's expected.
"""

from __future__ import annotations

from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin, PluginContext


class ShishenluPlugin(GameplayPlugin):
    """式神录 plugin — scaffold only, no gameplay defined yet."""

    name = "shishenlu"
    display_name = "式神录"

    # The scheduler validates these exist in the assembled graph before
    # starting the worker. `shishenlu.home` is contributed by this
    # plugin's own subgraph; `tingyuan` is the root home screen.
    requires_vertices = [
        "tingyuan",
        "shishenlu.home",
    ]

    # Where to land if `run()` raises. Inherited default is "main_menu"
    # which doesn't exist in this codebase yet; override to "tingyuan".
    SAFE_VERTEX = "tingyuan"

    @classmethod
    def build_subgraph(cls) -> GameGraph:
        from plugins.shishenlu.graph import build_subgraph as _build
        return _build()

    # ------------------------------------------------------------------ #
    # Lifecycle — placeholders. Replace `run()` with real gameplay.
    # ------------------------------------------------------------------ #
    def setup(self, ctx: PluginContext) -> None:
        ctx.logger.info("ShishenluPlugin: scaffold setup (no-op)")

    def run(self, ctx: PluginContext) -> None:
        ctx.logger.info(
            "ShishenluPlugin: no gameplay implemented yet; returning."
            " Replace plugin.run() to add real logic."
        )

    def teardown(self, ctx: PluginContext) -> None:
        ctx.logger.info("ShishenluPlugin: scaffold teardown (no-op)")
