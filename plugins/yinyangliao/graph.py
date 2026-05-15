from __future__ import annotations

from core.navigation import GameGraph, edge, external, subgraph, vertex
from core.navigation.builder import click_button
from graphs.main_buttons import HOME_RETURN_BTN
from plugins.yinyangliao.buttons import *


def build_subgraph() -> GameGraph:
    """Return the yinyangliao subgraph (unmerged)."""
    with subgraph("yinyangliao") as g:
        vertex(
            "home",
            name="阴阳寮主页",
            recognizer=YINYANGLIAO_ANCHOR,
            dwell_time=600,
        )

        # 返回庭院：用 root 的通用 "回主界面" 按钮（左上角房子图标）。
        # 如果阴阳寮有自己的关闭 X 按钮想用，可以在 buttons.py 里加一个
        # YINYANGLIAO_CLOSE_BTN 然后改这条 edge。
        # edge(
        #     "home", external("tingyuan"),
        #     action=click_button(HOME_RETURN_BTN),
        #     cost=1.0,
        # )

        edge(
            "home", external("tingyuan"),
            action=click_button(RETURN_BTN),
            cost=1.0,
        )

    return g
