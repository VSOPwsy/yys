from __future__ import annotations

from core.vision.button import Button

TANSUO_ANCHOR = Button.simple(
    "tansuo/tansuo_anchor",
    name="探索锚点",
    threshold=0.85,
)

YUHUN_ANCHOR = Button.simple(
    "tansuo/yuhun/yuhun_anchor",
    name="御魂副本锚点",
    threshold=0.95,
)

TANSUO_RETURN_BTN = Button.simple(
    "tansuo/tansuo_return_btn",
    name="探索返回按钮",
    threshold=0.85,
)

YUHUN_ENTRY_BTN = Button.simple(
    "tansuo/yuhun_entry_btn",
    name="御魂入口按钮",
    threshold=0.85,
)

YUHUN_RETURN_BTN = Button.simple(
    "tansuo/yuhun/yuhun_return_btn",
    name="御魂返回按钮",
    threshold=0.85,
)

__all__ = [
    "TANSUO_ANCHOR",
    "TANSUO_RETURN_BTN",
    "YUHUN_ENTRY_BTN",
    "YUHUN_ANCHOR",
    "YUHUN_RETURN_BTN",
]
