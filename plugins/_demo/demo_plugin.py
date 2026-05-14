"""
`DemoPlugin` — the Phase 3 reference plugin.

Behavior: bounce between `_demo.demo_screen_1` and `_demo.demo_screen_2`
five times, sleeping briefly between hops, then return to the root
`main_menu`. Polls `ctx.should_stop()` before every hop so F10 (stop
all) takes effect within at most one navigator call.

This is intentionally tiny — Phase 3's goal is the scheduler / hotkey /
threading machinery. Phase 4 will deliver the first real gameplay loop.
"""

from __future__ import annotations

from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin, PluginContext


class DemoPlugin(GameplayPlugin):
    """Minimal `GameplayPlugin` showing every lifecycle hook in action."""

    name = "_demo"
    display_name = "演示插件"
    # We rely on the root main_menu and our own two screens being present.
    # Listed for the scheduler's pre-flight check; if main_menu were missing
    # the worker would refuse to start instead of erroring deep inside run.
    requires_vertices = [
        "main_menu",
        "_demo.demo_screen_1",
        "_demo.demo_screen_2",
    ]

    LOOP_ITERATIONS = 5

    @classmethod
    def build_subgraph(cls) -> GameGraph:
        # Defer the actual graph build to the package's `graph.py` (the
        # convention all plugins follow) so this class file stays small.
        from plugins._demo.graph import build_subgraph
        return build_subgraph()

    def __init__(self) -> None:
        super().__init__()
        self.iterations_done = 0  # exposed for tests

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def setup(self, ctx: PluginContext) -> None:
        ctx.logger.info("DemoPlugin.setup: starting %d-iteration bounce",
                        self.LOOP_ITERATIONS)
        self.iterations_done = 0

    def run(self, ctx: PluginContext) -> None:
        for i in range(self.LOOP_ITERATIONS):
            # Cooperative stop check before each iteration.
            if ctx.should_stop():
                ctx.logger.info("DemoPlugin: stop requested at iteration %d", i)
                return
            # If paused, idle until resumed (or stopped).
            if ctx.should_pause():
                if ctx.wait_until_resumed():
                    return  # stop signalled while paused

            ctx.logger.info("DemoPlugin: iteration %d/%d", i + 1, self.LOOP_ITERATIONS)
            ctx.navigator.goto("_demo.demo_screen_2")
            if ctx.sleep(0.1):
                return
            ctx.navigator.goto("_demo.demo_screen_1")
            if ctx.sleep(0.1):
                return
            self.iterations_done = i + 1

        # All iterations done — head back to the root main menu.
        if ctx.should_stop():
            return
        ctx.logger.info("DemoPlugin: returning to main_menu")
        ctx.navigator.goto("main_menu")

    def teardown(self, ctx: PluginContext) -> None:
        ctx.logger.info(
            "DemoPlugin.teardown: completed %d/%d iterations",
            self.iterations_done, self.LOOP_ITERATIONS,
        )

    def on_pause(self, ctx: PluginContext) -> None:
        ctx.logger.info("DemoPlugin paused")

    def on_resume(self, ctx: PluginContext) -> None:
        ctx.logger.info("DemoPlugin resumed")
