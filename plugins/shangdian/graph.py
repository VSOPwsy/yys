from __future__ import annotations

from core.navigation import GameGraph, edge, external, subgraph, vertex
from core.navigation.builder import click_button
from graphs.main_buttons import HOME_RETURN_BTN
from plugins.shangdian.buttons import *


def build_subgraph() -> GameGraph:
    with subgraph("shangdian") as g:
        vertex(
            "home",
            name="商店主页",
            recognizer=SHANGDIAN_ANCHOR,
            dwell_time=600,
        )

        vertex(
            "rementuijian",
            name="热门推荐界面",
            recognizer=REMENTUIJIAN_ANCHOR,
            dwell_time=600,
        )

        vertex(
            "libaowu",
            name="礼包屋界面",
            recognizer=LIBAOWU_ANCHOR,
            dwell_time=600,
        )

        vertex(
            "shangdian.libaowu.richang",
            name="日常界面",
            recognizer=RICHANG_ANCHOR,
            dwell_time=600,
        )

        edge(
            "rementuijian", "home",
            action=click_button(SHANGDIAN_RETURN_BTN),
            cost=1.0,
        )
        
        edge(
            "rementuijian", "libaowu",
            action=click_button(LIBAOWU_ENTRY_BTN),
            cost=1.0,
        )

        edge(
            "home", "libaowu",
            action=click_button(LIBAOWU_ENTRY_BTN),
            cost=1.0,
        )

        edge(
            "libaowu", "shangdian.libaowu.richang",
            action=click_button(RICHANG_ENTRY_BTN),
            cost=1.0,
        )

        edge(
            "shangdian.libaowu.richang", "home",
            action=click_button(LIBAOWU_RETURN_BTN),
            cost=1.0,
        )

        edge(
            "libaowu", "home",
            action=click_button(LIBAOWU_RETURN_BTN),
            cost=1.0,
        )

        edge(
            "home", external("tingyuan"),
            action=click_button(SHANGDIAN_RETURN_BTN),
            cost=1.0,
        )
    return g
