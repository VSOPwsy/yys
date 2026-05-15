"""
Production root graph: the global screens every plugin can reach.

The root graph deliberately stays *thin*. It declares only the screens
that are universal to the game itself (the home screen, popups, generic
loading screens) and the edges between them that no plugin should own.

Anything game-mode-specific (daily sign-in panels, soul dungeon rooms,
exploration chapters) lives in `plugins/<name>/graph.py` and is merged
into this root at scheduler startup.

Adding a new plugin:
    1. Capture the plugin-specific anchor templates via
       ``dev_tools/template_extractor.py``.
    2. Add Buttons to ``plugins/<name>/buttons.py``.
    3. Build a subgraph in ``plugins/<name>/graph.py`` using bare names
       (they auto-prefix to ``<name>.*``).
    4. Cross from this root → plugin using ``external("<plugin>.entry")``
       on edges declared inside the subgraph, OR add the edge here
       referring to the qualified name.
    5. Register the plugin in ``config/config.yaml`` under the relevant
       account's ``plugins:`` section.

See `plugins/daily_reward/graph.py` for the reference pattern.
"""

from __future__ import annotations

from core.navigation import GameGraph, edge, external, root_graph, vertex
from core.navigation.builder import click_button, click_button_with_expand
from graphs.main_buttons import *


def build_main_graph() -> GameGraph:
    """Construct the root (no-namespace) graph for production runs."""
    with root_graph() as g:
        # 庭院主界面 —— 单一 vertex，识别只看 A 元素（TINGYUAN_ANCHOR）。
        # 庭院里那些"右下角折叠面板"的展开 / 收起子状态**不**进图——见
        # graphs/main_buttons.py 末尾的"折叠面板状态"段，及 CLAUDE.md。
        # 简单说：N 个独立折叠面板会把 vertex 数推到 2^N，所以折叠状态
        # 由插件用 `backend.find(MARKER)` 现场探测、按需点 hotspot 展开，
        # 不建模成 vertex。
        vertex(
            "tingyuan",
            name="庭院",
            recognizer=TINGYUAN_ANCHOR,
            # Home settles slowly after loading — give the screen a beat
            # before the next recognition tries to disambiguate.
            dwell_time=800,
        )

        vertex(
            "tingyuanshiwu",
            name="庭院事务",
            recognizer=TINGYUANSHIWU_ANCHOR,
            dwell_time=500,
        )

        # 注意：式神录是独立 plugin（plugins/shishenlu/），它的 home
        # vertex 是 `shishenlu.home`、由 plugin 子图贡献。这里没有
        # `shishenlu` root vertex —— 跨命名空间的入口边在下面用全限定
        # 名引用 `shishenlu.home`。

        # Generic popup screen. Many in-game events drop a modal on top of
        # whatever screen you were on; recognizing it gives the recovery
        # path a clear "close this and re-check" target instead of looping
        # on a wrong vertex.
        vertex(
            "popup",
            name="通用弹窗",
            recognizer=CLOSE_POPUP_BTN,
            dwell_time=300,
        )

        # popup -> tingyuan via the X button. Tagged as 'recovery' so
        # plugins can request paths that avoid this (it's cheap but
        # shouldn't be part of a "normal" route).
        edge(
            "popup", "tingyuan",
            action=click_button(CLOSE_POPUP_BTN),
            cost=1.0,
            tags=("recovery",),
        )

        # 庭院事务入口 —— 此按钮本身**不在折叠面板里**（它在庭院界面常驻
        # 可见），所以直接连边。如果哪天发现它其实也被折叠了，把
        # action 换成 `click_button_with_expand(TINGYUANSHIWU_ENTRY_BTN,
        # TINGYUAN_EXPAND_HOTSPOT)` 即可，不用改任何 plugin。
        edge(
            "tingyuan", "tingyuanshiwu",
            action=click_button(TINGYUANSHIWU_ENTRY_BTN),
            cost=1.2,
        )

        # 式神录入口 —— 此按钮**藏在折叠面板里**，平时找不到。
        # `click_button_with_expand` 在执行 edge 时先 find，找不到就
        # 在 HOTSPOT 矩形内随机一点 click_xy 展开、等 1 秒、再 click。
        # PathFinder / Plugin / Navigator 都无需感知折叠存在。
        #
        # 跨命名空间引用：`shishenlu.home` 是 plugins/shishenlu/graph.py
        # 注册的 vertex。带点 → DSL 原样保留，不需要 external()。
        # 若 shishenlu plugin 未在 config.yaml 启用，其子图不会被合并、
        # 这条 edge 在 GraphAssembler 阶段会被当成 dangling 删除并 warn。
        edge(
            "tingyuan", "shishenlu.home",
            action=click_button_with_expand(
                SHISHENLU_ENTRY_BTN, TINGYUAN_EXPAND_HOTSPOT,
            ),
            cost=1.5,
        )

        edge(
            "tingyuan", "shangdian.home",
            action=click_button_with_expand(
                SHANGDIAN_ENTRY_BTN, TINGYUAN_EXPAND_HOTSPOT,
            ),
            cost=1.5,
        )

        edge(
            "tingyuan", "yinyangliao.home",
            action=click_button_with_expand(
                YINYANGLIAO_ENTRY_BTN, TINGYUAN_EXPAND_HOTSPOT,
            ),
            cost=1.5,
        )

    return g
