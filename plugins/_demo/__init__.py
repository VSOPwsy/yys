"""
`_demo` — minimal Phase 3 example plugin.

Demonstrates:
    * The full `GameplayPlugin` lifecycle (setup / run / teardown +
      pause / resume hooks).
    * Cooperative stop via `ctx.should_stop()` / `ctx.sleep()`.
    * Subgraph composition with a cross-namespace return edge.
    * Static `Button` definitions in `buttons.py` (convention for real
      plugins; the demo itself runs against a `FakeBackend` and does
      not actually match templates).

Run via `main.py`.
"""

from plugins._demo.demo_plugin import DemoPlugin
from plugins._demo.graph import build_subgraph

__all__ = ["DemoPlugin", "build_subgraph"]
