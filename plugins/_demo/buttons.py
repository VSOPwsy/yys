"""
Button definitions for the `_demo` plugin.

Convention: each plugin keeps all of its `Button` objects in one module,
imported by both `graph.py` (used inside edge actions) and the plugin
class (for `requires_vertices` or direct use). This makes "what does
this plugin touch on screen" answerable by reading one file.

The actual demo plugin runs against a `FakeBackend` and never invokes
these buttons — they exist as documentation of the intended convention.
A real plugin would point the `template` paths at PNGs under
``templates/<plugin_name>/``.
"""

from __future__ import annotations

from core.vision.button import Button

# Screen-1 marker — for example, the "Go to screen 2" call-to-action.
DEMO_SCREEN_1_MARKER = Button.simple(
    "_demo/screen_1_marker",
    name="演示界面 1 标识",
)

# Screen-2 marker — the "Back to screen 1" call-to-action.
DEMO_SCREEN_2_MARKER = Button.simple(
    "_demo/screen_2_marker",
    name="演示界面 2 标识",
)

# Back button on screen 2 that returns to the main menu.
BACK_TO_MAIN_BTN = Button.simple(
    "_demo/back_to_main_btn",
    name="返回主菜单",
)
