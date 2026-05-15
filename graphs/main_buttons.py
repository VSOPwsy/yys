"""
Root-namespace `Button` definitions for the production game graph.

These are the UI anchors that identify Onmyoji's *global* screens —
home/tingyuan menu, the sign-in modal entry, etc. Plugin-specific UI lives
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
       home screen (this is what `TINGYUAN_ANCHOR` looks for).
    4. Press ``C``, save as ``tingyuan/tingyuan_anchor``.
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
# Home / tingyuan menu
# ----------------------------------------------------------------------- #
# The default home screen of Onmyoji ("庭院/Yard"). Anchor on a unique UI
# element — typically the top-left ribbon or a corner widget that is only
# visible on the home screen.
TINGYUAN_ANCHOR = Button.simple(
    "tingyuan/tingyuan_anchor",
    name="主界面锚点",
    threshold=0.85,
)

## 庭院事务锚点
TINGYUANSHIWU_ANCHOR = Button.simple(
    "tingyuan/tingyuanshiwu/tingyuanshiwu_anchor",
    name="庭院事务锚点",
    threshold=0.85,
)

# Entry into the daily sign-in flow from the home screen. Typically a
# button on the home screen's right-side panel, or a banner pop-up.
TINGYUANSHIWU_ENTRY_BTN = Button.simple(
    "tingyuan/tingyuanshiwu_entry_btn",
    name="庭院事务入口",
    threshold=0.85,
    post_delay=0.8,
)

# ----------------------------------------------------------------------- #
# 庭院折叠面板 —— 状态而非 vertex
# ----------------------------------------------------------------------- #
# 庭院右下角有一个可折叠面板，平时收起、点击热区后展开露出若干入口
# 按钮（式神录 / ...）。**这是状态，不进 graph**——原因：N 个独立折叠
# 面板会把 vertex 数推到 2^N，是 graph 模型撑不住的拓扑。
#
# 两种使用方式，按场景选：
#
# (1) 折叠按钮指向的是图里的某个 vertex（首选）——直接在 edge 上用
#     `click_button_with_expand`，PathFinder 平时不需要知道折叠存在，
#     执行 edge 时自动 ensure expand：
#
#         from core.navigation.builder import click_button_with_expand
#         edge(
#             "tingyuan", "shishenlu",
#             action=click_button_with_expand(
#                 SHISHENLU_ENTRY_BTN, TINGYUAN_EXPAND_HOTSPOT,
#             ),
#             cost=1.5,
#         )
#
#     已经这么在 graphs/main.py 给 shishenlu 接好了，可以照抄。
#
# (2) 折叠按钮的点击不是 "去另一个 vertex"（比如插件只是想读一下面板
#     上的某个数字、看一眼当前签到状态），在 plugin step 里内联：
#
#         from core.humanize import random_point_in_rect
#         from graphs.main_buttons import SHISHENLU_ENTRY_BTN, TINGYUAN_EXPAND_HOTSPOT
#
#         def peek_something(ctx):
#             ctx.navigator.goto("tingyuan")  # graph 保证到庭院
#             if ctx.backend.find(SHISHENLU_ENTRY_BTN) is None:
#                 ctx.backend.click_xy(*random_point_in_rect(TINGYUAN_EXPAND_HOTSPOT))
#                 ctx.sleep(1.0)              # 等展开动画
#             ...  # 读取 / 检查，但不 click_button(SHISHENLU_ENTRY_BTN)

# 式神录入口按钮 —— 仅在庭院折叠面板*展开*后可见。
# 视觉上这枚按钮在庭院里（折叠面板属于庭院帧），所以它的 Button
# 定义留在这个文件里。而式神录内屏的锚点（识别"在式神录"用）和
# 式神录后续 plugin 内部的按钮放在 plugins/shishenlu/buttons.py。
# 它同时承担两个角色：
#   1. 上面 pattern 里 `find(SHISHENLU_ENTRY_BTN) is None` 当作"未展开"
#      的状态判定（没必要再为它单独抠一个"展开标识 marker"）。
#   2. 真正的点击目标 —— 展开后 `click(SHISHENLU_ENTRY_BTN)` 进式神录。
SHISHENLU_ENTRY_BTN = Button.simple(
    "tingyuan/shishenlu_entry_btn",
    name="式神录入口",
    threshold=0.85,
    post_delay=0.8,
)

# 庭院折叠面板的切换热区。无视觉特征 → 不能做成 Button。
# 用**矩形** ``(x1, y1, x2, y2)`` 而不是单点 ``(x, y)``，原因：
#     单点会把"哪里点都行"的安全范围压缩到 backend 自身 ±3px 的微抖动，
#     拟人化没空间发挥。矩形让 `random_point_in_rect()` 在整个安全区
#     里均匀采样，backend 再在采样点上叠加微抖动，两层节奏。
# 真机量法：dev_tools/template_extractor.py 截图后，框出**整个**视觉
# 上安全的右下角空白区域（点哪都能触发展开但又不会误点别的按钮），
# 取这个框的 ADB 坐标。
TINGYUAN_EXPAND_HOTSPOT = (1792, 896, 1856, 1046)


SHANGDIAN_ENTRY_BTN = Button.simple(
    "tingyuan/shangdian_entry_btn",
    name="商店入口",
    threshold=0.85,
    post_delay=0.8,
)

YINYANGLIAO_ENTRY_BTN = Button.simple(
    "tingyuan/yinyangliao_entry_btn",
    name="阴阳寮入口",
    threshold=0.85,
    post_delay=0.8,
)



# Universal "back to home" button: the upper-left house/back icon shown
# on most sub-screens. Daily Reward's recovery path uses this.
HOME_RETURN_BTN = Button.simple(
    "tingyuan/home_return_btn",
    name="返回主界面",
    threshold=0.82,
    post_delay=1.0,
)

# Universal "close popup" button: the 'X' shown on most modal dialogs.
# Defensive recoverers click this when something unexpected covers the
# UI (login bonus modal, announcement, etc.).
CLOSE_POPUP_BTN = Button.simple(
    "tingyuan/close_popup_btn",
    name="关闭弹窗",
    threshold=0.85,
    post_delay=0.6,
)

__all__ = [
    "CLOSE_POPUP_BTN",
    "HOME_RETURN_BTN",
    "TINGYUAN_ANCHOR",
    "TINGYUAN_EXPAND_HOTSPOT",
    "TINGYUANSHIWU_ANCHOR",
    "TINGYUANSHIWU_ENTRY_BTN",
    "SHISHENLU_ENTRY_BTN",
    "SHANGDIAN_ENTRY_BTN",
    "YINYANGLIAO_ENTRY_BTN",
]
