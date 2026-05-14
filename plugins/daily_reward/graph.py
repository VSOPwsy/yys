"""
Subgraph for the daily-reward plugin.

Owns exactly one screen: ``daily_reward.sign_in_panel`` (the in-game
"签到/Daily Sign-in" modal). The transitions between the root home
screen and this panel cross the namespace boundary:

* root → panel: declared in ``graphs/main.py`` because the home button
  that opens the panel is the root's UI element.

* panel → root: declared here, because closing the panel is a panel-
  internal action and the dst is referenced via ``external("main_menu")``.

This split matches CLAUDE.md S5: each vertex has exactly one owner,
edges live on the side that defines the action.
"""

from __future__ import annotations

from core.navigation import GameGraph, edge, external, subgraph, vertex
from core.navigation.builder import click_button
from plugins.daily_reward.buttons import (
    SIGN_IN_CLOSE_BTN,
    SIGN_IN_PANEL_ANCHOR,
)


def build_subgraph() -> GameGraph:
    """Return the daily_reward subgraph (unmerged)."""
    with subgraph("daily_reward") as g:
        vertex(
            "sign_in_panel",
            name="签到面板",
            recognizer=SIGN_IN_PANEL_ANCHOR,
            # Sign-in animations take a moment to settle.
            dwell_time=900,
        )

        # Closing the modal returns to the home screen. `external()`
        # is required because `main_menu` is the root namespace's vertex,
        # and bare names inside `subgraph("daily_reward")` auto-prefix to
        # `daily_reward.*`.
        edge(
            "sign_in_panel", external("main_menu"),
            action=click_button(SIGN_IN_CLOSE_BTN),
            cost=1.0,
        )

    return g
