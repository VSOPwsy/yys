from __future__ import annotations

from core.navigation import GameGraph, edge, external, subgraph, vertex
from core.navigation.builder import click_button
from graphs.main_buttons import HOME_RETURN_BTN
from plugins.tansuo.buttons import *


def build_subgraph() -> GameGraph:
    """Return the tansuo subgraph (unmerged)."""
    with subgraph("tansuo") as g:
        vertex(
            "home",
            name="探索主页",
            recognizer=TANSUO_ANCHOR,
            dwell_time=600,
        )

        vertex(
            "yuhun",
            name="御魂副本界面",
            recognizer=YUHUN_ANCHOR,
            dwell_time=600,
        )

        edge(
            "home", "yuhun",
            action=click_button(YUHUN_ENTRY_BTN),
            cost=1.0,
        )

        edge(
            "yuhun", "home",
            action=click_button(YUHUN_RETURN_BTN),
            cost=1.0,
        )

        edge(
            "home", external("tingyuan"),
            action=click_button(TANSUO_RETURN_BTN),
            cost=1.0,
        )

    return g
