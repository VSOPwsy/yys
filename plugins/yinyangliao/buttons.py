from __future__ import annotations

from core.vision.button import Button

YINYANGLIAO_ANCHOR = Button.simple(
    "yinyangliao/yinyangliao_anchor",
    name="阴阳寮锚点",
    threshold=0.85,
)

RETURN_BTN = Button.simple(
    "yinyangliao/return_btn",
    name="阴阳寮返回按钮",
    threshold=0.85,
)

__all__ = [
    "YINYANGLIAO_ANCHOR",
    "RETURN_BTN",
]
