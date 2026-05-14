"""
Root-namespace `Button` definitions for the production game graph.

These are the UI anchors that identify Onmyoji's *global* screens —
home/main menu, the sign-in modal entry, etc. Plugin-specific UI lives
in `plugins/<name>/buttons.py`; this file is reserved for things every
plugin can refer to.

Templates are referenced by logical name relative to ``templates/``
(no ``.png`` suffix). The PNGs themselves must be captured by the
operator via ``dev_tools/template_extractor.py`` against a live
emulator — this module only fixes the *contracts* (path, threshold,
search region) so the rest of the system has stable references to point
at.

Capture checklist (one-time, per game install):
    1. Boot MuMu + Onmyoji, sit on the home screen.
    2. Run ``python dev_tools/template_extractor.py --mumu <root>``.
    3. Drag a tight box around the **upper-left banner / logo** of the
       home screen (this is what `MAIN_MENU_ANCHOR` looks for).
    4. Press ``C``, save as ``main/main_menu_anchor``.
    5. Repeat for the other anchors listed below.

Why anchors and not full-screen matches:
    A single 50x50 unique anchor matches faster than a 1920x1080 frame
    comparison, and tolerates UI variations (banners, popups) that touch
    most of the screen. Pick anchors that are immutable across game
    states — logo glyphs, unchanging menu chrome, etc.
"""

from __future__ import annotations

from core.vision.button import Button

# ----------------------------------------------------------------------- #
# Home / main menu
# ----------------------------------------------------------------------- #
# The default home screen of Onmyoji ("庭院/Yard"). Anchor on a unique UI
# element — typically the top-left ribbon or a corner widget that is only
# visible on the home screen.
MAIN_MENU_ANCHOR = Button.simple(
    "main/main_menu_anchor",
    name="主界面锚点",
    threshold=0.85,
)

# Entry into the daily sign-in flow from the home screen. Typically a
# button on the home screen's right-side panel, or a banner pop-up.
SIGN_IN_ENTRY_BTN = Button.simple(
    "main/sign_in_entry_btn",
    name="签到入口",
    threshold=0.85,
    post_delay=0.8,
)

# Universal "back to home" button: the upper-left house/back icon shown
# on most sub-screens. Daily Reward's recovery path uses this.
HOME_RETURN_BTN = Button.simple(
    "main/home_return_btn",
    name="返回主界面",
    threshold=0.82,
    post_delay=1.0,
)

# Universal "close popup" button: the 'X' shown on most modal dialogs.
# Defensive recoverers click this when something unexpected covers the
# UI (login bonus modal, announcement, etc.).
CLOSE_POPUP_BTN = Button.simple(
    "main/close_popup_btn",
    name="关闭弹窗",
    threshold=0.85,
    post_delay=0.6,
)

__all__ = [
    "CLOSE_POPUP_BTN",
    "HOME_RETURN_BTN",
    "MAIN_MENU_ANCHOR",
    "SIGN_IN_ENTRY_BTN",
]
