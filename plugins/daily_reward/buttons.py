"""
`Button` definitions exclusive to the daily-reward plugin.

Convention: every Button this plugin clicks or recognizes lives here.
Imports stay in one place so reviewers (and your future self) can answer
"what does this plugin touch on screen" by reading one file.

Templates live at ``templates/daily_reward/<name>.png``. Capture them via
``dev_tools/template_extractor.py``; do not hand-edit. See the package
README for the capture checklist.
"""

from __future__ import annotations

from core.vision.button import Button

# ---- screen anchors ----------------------------------------------------- #

# Unique element of the sign-in modal — e.g. the title bar reading "签到"
# or the calendar-grid chrome that only appears here. Used as the
# recognizer for the `daily_reward.sign_in_panel` vertex.
SIGN_IN_PANEL_ANCHOR = Button.simple(
    "daily_reward/sign_in_panel_anchor",
    name="签到面板锚点",
    threshold=0.85,
)

# Anchor for the "today's reward already claimed" state. Drawn over the
# claim button after a successful claim — recognizing it lets us short-
# circuit on the no-op case (already claimed earlier today).
ALREADY_CLAIMED_ANCHOR = Button.simple(
    "daily_reward/already_claimed_anchor",
    name="今日已领取",
    threshold=0.86,
)

# ---- action buttons ----------------------------------------------------- #

# The big "领取/Claim today" button on the daily sign-in modal.
CLAIM_TODAY_BTN = Button.simple(
    "daily_reward/claim_today_btn",
    name="领取今日奖励",
    threshold=0.85,
    post_delay=1.2,  # game spawns the reward animation; give it time.
)

# The "好的/Confirm" or "X" on the reward popup that appears after claim.
CONFIRM_REWARD_BTN = Button.simple(
    "daily_reward/confirm_reward_btn",
    name="确认奖励",
    threshold=0.85,
    post_delay=0.8,
)

# Defensive "close" on the sign-in modal itself — used when something
# unexpected put us back on the panel during recovery.
SIGN_IN_CLOSE_BTN = Button.simple(
    "daily_reward/sign_in_close_btn",
    name="关闭签到面板",
    threshold=0.85,
    post_delay=0.8,
)

# ---- OCR target regions ------------------------------------------------- #
# These are not Buttons — they are screenshot crops we hand to OCR to read
# the reward count. Defined as plain tuples here so steps.py imports them.

# (x1, y1, x2, y2) ADB-coordinate box covering the reward count text on
# the post-claim popup. Adjust per resolution; defaults assume 1280x720.
REWARD_COUNT_REGION = (480, 320, 800, 410)

__all__ = [
    "ALREADY_CLAIMED_ANCHOR",
    "CLAIM_TODAY_BTN",
    "CONFIRM_REWARD_BTN",
    "REWARD_COUNT_REGION",
    "SIGN_IN_CLOSE_BTN",
    "SIGN_IN_PANEL_ANCHOR",
]
