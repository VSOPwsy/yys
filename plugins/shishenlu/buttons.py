"""
`Button` definitions exclusive to the 式神录 plugin.

Per README §5.2.4 ("模板目录组织规则"): only buttons that **visually
live inside the 式神录 screen** belong here. The entry button shown in
the 庭院 fold panel stays in ``graphs/main_buttons.py`` because it
visually lives in 庭院 (the button's image is on the 庭院 frame, even
though clicking it leads here).

Templates live at ``templates/shishenlu/<name>.png``. Capture them via
``dev_tools/template_extractor.py``.
"""

from __future__ import annotations

from core.vision.button import Button

# ---- screen anchors ----------------------------------------------------- #

# 式神录界面的锚点 —— 用于 `shishenlu.home` vertex 的 recognizer，确认
# 我们真的进了式神录而不是半路过渡帧。抠的时候选一个**只在式神录界面
# 才出现**的元素：页签 / 默认头像格 / 顶部 banner 等。
SHISHENLU_ANCHOR = Button.simple(
    "shishenlu/shishenlu_anchor",
    name="式神录锚点",
    threshold=0.85,
)

__all__ = [
    "SHISHENLU_ANCHOR",
]
