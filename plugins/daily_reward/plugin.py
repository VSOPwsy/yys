"""
`DailyRewardPlugin` — Phase 4 reference gameplay implementation.

Walks the player from wherever they are → daily sign-in panel → claim
today's reward → OCR the reward count → back to main_menu. Designed to
be the canonical example of a real gameplay plugin: small, complete,
well-tested.

Lifecycle:
    setup        — log start; nothing to warm up.
    run          — single pass through the daily reward flow. Returns
                   normally on success (worker transitions to STOPPED).
    teardown     — log result.
    on_pause /
    on_resume    — default no-ops; the flow is short enough that pause
                   support is largely cosmetic. Listed for symmetry.

Failure modes are handled by the base-class `handle_unexpected_error`
which the worker invokes automatically — see CLAUDE.md §6
``core/scheduler/plugin_base.py`` for the contract.
"""

from __future__ import annotations

from core.exceptions import NavigationError
from core.navigation.graph import GameGraph
from core.scheduler.plugin_base import GameplayPlugin, PluginContext
from plugins.daily_reward import steps


class DailyRewardPlugin(GameplayPlugin):
    """One-shot daily sign-in / reward claim."""

    name = "daily_reward"
    display_name = "每日签到"

    # Vertices we read or land on. The scheduler verifies these exist in
    # the assembled graph before starting the worker, so a typo here
    # surfaces as `PluginRequirementUnmet` at startup, not a navigator
    # crash mid-run.
    requires_vertices = [
        "main_menu",
        "daily_reward.sign_in_panel",
    ]

    # Where to land if `run()` raises unexpectedly. Inherited default is
    # already "main_menu"; listed here so the override path is obvious.
    SAFE_VERTEX = "main_menu"

    @classmethod
    def build_subgraph(cls) -> GameGraph:
        from plugins.daily_reward.graph import build_subgraph as _build
        return _build()

    def __init__(self) -> None:
        super().__init__()
        # Exposed for tests + the teardown log message.
        self.claimed = False
        self.reward_count: int | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def setup(self, ctx: PluginContext) -> None:
        ctx.logger.info("DailyRewardPlugin: starting daily-reward flow")
        self.claimed = False
        self.reward_count = None

    def run(self, ctx: PluginContext) -> None:
        if ctx.should_stop():
            return
        steps.open_sign_in_panel(ctx)

        if ctx.should_stop():
            return
        if steps.is_already_claimed(ctx):
            ctx.logger.info("DailyRewardPlugin: today's reward already claimed")
            self.claimed = False
            steps.return_to_main_menu(ctx)
            return

        if ctx.should_stop():
            return
        ok = steps.claim_today(ctx)
        if not ok:
            ctx.logger.info(
                "DailyRewardPlugin: claim button absent — treating as no-op"
            )
            steps.return_to_main_menu(ctx)
            return
        self.claimed = True

        # Reading the reward count is best-effort; absence of OCR or a
        # bad crop does not invalidate the claim itself.
        if not ctx.should_stop():
            self.reward_count = steps.read_reward_count(ctx)
            ctx.logger.info(
                "DailyRewardPlugin: reward_count=%r", self.reward_count
            )

        if ctx.should_stop():
            return
        steps.confirm_reward_popup(ctx)

        if ctx.should_stop():
            return
        steps.return_to_main_menu(ctx)

    def teardown(self, ctx: PluginContext) -> None:
        ctx.logger.info(
            "DailyRewardPlugin done: claimed=%s reward_count=%r",
            self.claimed, self.reward_count,
        )

    # ------------------------------------------------------------------ #
    # Recovery override: if we fail mid-flow, try to close the panel
    # first (it's modal and would otherwise block the home-navigator).
    # ------------------------------------------------------------------ #
    def handle_unexpected_error(
        self,
        ctx: PluginContext,
        exc: BaseException,
    ) -> bool:
        # Save the screenshot first via super() so we always have the
        # forensic artifact even if the in-panel close also fails.
        self.save_error_screenshot(ctx, exc)
        # Best-effort: if we recognize we're still on the sign-in panel,
        # press the close button before falling through to the standard
        # main-menu recovery.
        try:
            if ctx.navigator.is_at("daily_reward.sign_in_panel"):
                ctx.logger.info(
                    "recovery: still on sign_in_panel, attempting close"
                )
                from plugins.daily_reward.buttons import SIGN_IN_CLOSE_BTN
                try:
                    ctx.backend.click(SIGN_IN_CLOSE_BTN)
                except Exception as e:  # noqa: BLE001
                    ctx.logger.warning(
                        "recovery close-button click failed: %s", e
                    )
        except NavigationError as e:
            ctx.logger.debug("recovery: is_at check raised %s", e)
        # Standard retry-to-main-menu loop.
        for attempt in range(1, self.MAX_RECOVERY_ATTEMPTS + 1):
            if ctx.should_stop():
                return False
            ctx.logger.info(
                "recovery attempt %d/%d", attempt, self.MAX_RECOVERY_ATTEMPTS
            )
            if self.recover_to_main(ctx):
                return True
        return False
