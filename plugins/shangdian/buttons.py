from __future__ import annotations

from core.vision.button import Button

SHANGDIAN_ANCHOR = Button.simple(
    "shangdian/shangdian_anchor",
    name="商店锚点",
    threshold=0.85,
)

SHANGDIAN_RETURN_BTN = Button.simple(
    "shangdian/shangdian_return_btn",
    name="商店返回按钮",
    threshold=0.85,
)

REMENTUIJIAN_ANCHOR = Button.simple(
    "shangdian/rementuijian/rementuijian_anchor",
    name="热门推荐锚点",
    threshold=0.85,
)

LIBAOWU_ANCHOR = Button.simple(
    "shangdian/libaowu/libaowu_anchor",
    name="礼包屋锚点",
    threshold=0.85,
)

LIBAOWU_ENTRY_BTN = Button.simple(
    "shangdian/libaowu_entry_btn",
    name="礼包屋入口按钮",
    threshold=0.85,
)

RICHANG_ENTRY_BTN = Button.simple(
    "shangdian/libaowu/richang_entry_btn",
    name="日常入口按钮",
    threshold=0.97,
)

RICHANG_ANCHOR = Button.simple(
    "shangdian/libaowu/richang/richang_anchor",
    name="日常锚点",
    threshold=0.98,
)

LIBAOWU_RETURN_BTN = Button.simple(
    "shangdian/libaowu/libaowu_return_btn",
    name="礼包屋返回按钮",
    threshold=0.85,
)

__all__ = [
    "SHANGDIAN_ANCHOR",
    "SHANGDIAN_RETURN_BTN",
    "REMENTUIJIAN_ANCHOR",
    "LIBAOWU_ANCHOR",
    "LIBAOWU_ENTRY_BTN",
    "RICHANG_ENTRY_BTN",
    "RICHANG_ANCHOR",
    "LIBAOWU_RETURN_BTN",
]
