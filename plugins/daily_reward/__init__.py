"""
`daily_reward` — first real Phase 4 gameplay plugin.

Walks through the Onmyoji daily sign-in flow and returns to the home
screen. Concrete reference implementation of every Phase 4 contract:

  * `GameplayPlugin` subclass with `requires_vertices` declared,
  * subgraph composition via `external(main_menu)` for cross-namespace
    transitions,
  * step functions broken out for testability,
  * humanize-friendly navigation (`navigator.goto(humanize=True)`),
  * OCR-driven reward count parsing (best-effort, soft-fails),
  * plugin-specific `handle_unexpected_error` override.

See the package `README.md` for the operator's checklist of templates
to capture before the plugin can run on a real emulator.
"""

from plugins.daily_reward.plugin import DailyRewardPlugin

__all__ = ["DailyRewardPlugin"]
