"""
Subgraph for the 式神录 plugin.

Owns one vertex: ``shishenlu.home`` — the 式神录 landing screen
(default shikigami-list view). The cross-namespace transitions:

* root → ``shishenlu.home``: declared in ``graphs/main.py`` because the
  entry button (``SHISHENLU_ENTRY_BTN``) lives in the 庭院 fold panel,
  i.e. visually belongs to the root namespace. That edge uses
  ``click_button_with_expand`` so PathFinder doesn't have to know about
  the fold.

* ``shishenlu.home`` → root: declared here (closing / backing out of
  式神录 is a panel-internal action). Destination via
  ``external("tingyuan")``.

This matches the pattern in ``plugins/daily_reward/graph.py``.
"""

from __future__ import annotations

from core.navigation import GameGraph, edge, external, subgraph, vertex
from core.navigation.builder import click_button
from graphs.main_buttons import HOME_RETURN_BTN
from plugins.shishenlu.buttons import *


def build_subgraph() -> GameGraph:
    """Return the shishenlu subgraph (unmerged)."""
    with subgraph("shishenlu") as g:
        vertex(
            "home",
            name="式神录主页",
            recognizer=SHISHENLU_ANCHOR,
            dwell_time=600,
        )

        # 返回庭院：用 root 的通用 "回主界面" 按钮（左上角房子图标）。
        # 如果式神录有自己的关闭 X 按钮想用，可以在 buttons.py 里加一个
        # SHISHENLU_CLOSE_BTN 然后改这条 edge。
        edge(
            "home", external("tingyuan"),
            action=click_button(HOME_RETURN_BTN),
            cost=1.0,
        )

    return g
