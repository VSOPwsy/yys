"""
Individual steps that compose the daily-reward gameplay loop.

Each step is a free function taking the active `PluginContext`. Keeping
them out of the plugin class means:
    * they're individually unit-testable (mock the ctx),
    * they can be reordered or skipped without touching the orchestrator,
    * other plugins can borrow them via direct import if the UI overlaps.

The steps are intentionally *small* — one user-visible state transition
each. The orchestrator (`plugin.py::DailyRewardPlugin.run`) is the only
file that knows the full sequence.
"""

from __future__ import annotations

import re
from typing import Optional

from core.exceptions import MatchTimeout
from core.scheduler.plugin_base import PluginContext
from plugins.daily_reward.buttons import (
    ALREADY_CLAIMED_ANCHOR,
    CLAIM_TODAY_BTN,
    CONFIRM_REWARD_BTN,
    REWARD_COUNT_REGION,
    SIGN_IN_PANEL_ANCHOR,
)


# Regex matching common reward-count formats: "x100", "×100", "×100", "100".
# OCR routinely confuses '×' with 'x' / 'X', so we accept any of them.
_REWARD_COUNT_RE = re.compile(r"[x×X]?\s*(\d{1,6})")


def open_sign_in_panel(ctx: PluginContext) -> None:
    """Navigate to ``daily_reward.sign_in_panel`` from wherever we are.

    Uses the Navigator's humanize mode so repeated runs don't always pick
    the exact same path (matters if the graph has multiple routes to the
    panel — currently it doesn't, but the principle is locked in).
    """
    ctx.logger.info("daily_reward: navigating to sign_in_panel")
    ctx.navigator.goto("daily_reward.sign_in_panel", humanize=True)


def is_already_claimed(ctx: PluginContext) -> bool:
    """True iff the "today already claimed" anchor is visible on screen.

    Cheap pre-check that lets the plugin short-circuit on no-op runs
    (the operator forgot to clear yesterday's state, or the cron fired
    twice). Returns False on any matcher error — we'd rather attempt the
    claim than silently skip.
    """
    try:
        return ctx.backend.is_visible(ALREADY_CLAIMED_ANCHOR)
    except Exception as e:  # noqa: BLE001
        ctx.logger.debug(
            "is_already_claimed: matcher raised %s — assuming not claimed", e
        )
        return False


def claim_today(ctx: PluginContext) -> bool:
    """Tap the claim button. Returns False if the button wasn't visible.

    Soft-fail (rather than raise) because the "already claimed" anchor
    can sometimes hide the claim button without our pre-check catching
    it — better to log + skip than to escalate to recovery.
    """
    try:
        ctx.backend.click(CLAIM_TODAY_BTN)
    except MatchTimeout:
        ctx.logger.info(
            "claim_today: button not visible — likely already claimed today"
        )
        return False
    return True


def read_reward_count(ctx: PluginContext) -> Optional[int]:
    """OCR the reward popup's count text. Returns None on any failure.

    Returning None instead of raising lets the orchestrator decide whether
    to continue (the rest of the loop doesn't depend on a successful read
    — the reward is already in the player's inventory by the time we OCR).

    Requires the OCR engine wired into `ctx.ocr`. If absent (Phase 1-3
    default until ``paddleocr`` is installed), this becomes a no-op that
    logs and returns None.
    """
    if ctx.ocr is None:
        ctx.logger.info("read_reward_count: ocr engine not configured; skipping")
        return None

    try:
        shot = ctx.backend.screenshot()
    except Exception as e:  # noqa: BLE001
        ctx.logger.warning("read_reward_count: screenshot raised %s", e)
        return None

    x1, y1, x2, y2 = REWARD_COUNT_REGION
    # Bounds-check the crop against the screenshot dimensions; OCR will
    # error out on a 0x0 array but the clearer log message helps debug.
    h, w = shot.shape[:2]
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        ctx.logger.warning(
            "read_reward_count: region %r out of bounds (image %dx%d)",
            REWARD_COUNT_REGION, w, h,
        )
        return None
    crop = shot[y1:y2, x1:x2]
    try:
        results = ctx.ocr.recognize(crop)
    except Exception as e:  # noqa: BLE001
        ctx.logger.warning("read_reward_count: ocr.recognize raised %s", e)
        return None

    # results is List[(text, confidence, bbox)]; concatenate text and
    # regex out the first sensible-looking integer.
    joined = " ".join(t for t, _conf, _bbox in results)
    match = _REWARD_COUNT_RE.search(joined)
    if not match:
        ctx.logger.info("read_reward_count: no integer in OCR output %r", joined)
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def confirm_reward_popup(ctx: PluginContext) -> None:
    """Dismiss the post-claim "got X item" modal. Silent if not present."""
    try:
        ctx.backend.click(CONFIRM_REWARD_BTN)
    except MatchTimeout:
        ctx.logger.debug(
            "confirm_reward_popup: button not visible — popup likely auto-closed"
        )


def return_to_main_menu(ctx: PluginContext) -> None:
    """Final step: explicitly walk back to ``main_menu``.

    Plugins SHOULD end at `main_menu` so the next plugin (or operator)
    inherits a known-good state. Idempotent — navigating to where we
    already are is a no-op.
    """
    ctx.logger.info("daily_reward: returning to main_menu")
    ctx.navigator.goto("main_menu", humanize=True)


# Public surface — explicit __all__ so reviewers know which functions
# are intended to be called from plugin.py.
__all__ = [
    "claim_today",
    "confirm_reward_popup",
    "is_already_claimed",
    "open_sign_in_panel",
    "read_reward_count",
    "return_to_main_menu",
]
