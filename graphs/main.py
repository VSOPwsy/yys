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
from core.navigation.builder import click_button
from graphs.main_buttons import (
    CLOSE_POPUP_BTN,
    HOME_RETURN_BTN,
    MAIN_MENU_ANCHOR,
    SIGN_IN_ENTRY_BTN,
)


def build_main_graph() -> GameGraph:
    """Construct the root (no-namespace) graph for production runs."""
    with root_graph() as g:
        # The home screen is the canonical "we are at a known good state".
        # Every plugin's error-recovery path lands here.
        vertex(
            "main_menu",
            name="主界面",
            recognizer=MAIN_MENU_ANCHOR,
            # Home settles slowly after loading — give the screen a beat
            # before the next recognition tries to disambiguate.
            dwell_time=800,
        )

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

        # popup -> main_menu via the X button. Tagged as 'recovery' so
        # plugins can request paths that avoid this (it's cheap but
        # shouldn't be part of a "normal" route).
        edge(
            "popup", "main_menu",
            action=click_button(CLOSE_POPUP_BTN),
            cost=1.0,
            tags=("recovery",),
        )

        # Entry into the daily sign-in flow. The destination lives inside
        # the daily_reward plugin's namespace — we use external() to keep
        # the bare 'daily_reward.sign_in_panel' from being mistaken for a
        # relative name in this root context.
        edge(
            "main_menu", external("daily_reward.sign_in_panel"),
            action=click_button(SIGN_IN_ENTRY_BTN),
            cost=1.2,
        )

    return g
