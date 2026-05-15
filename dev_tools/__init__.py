"""
Dev-only tooling. Per CLAUDE.md §3, **never** imported by core / plugins /
main.py — production code does not depend on these scripts. The reverse
is fine: dev_tools modules can import from core, graphs, plugins.

This ``__init__.py`` exists only so `dev_tools` is a proper package and
modules inside it can reference each other via dotted import (e.g.
``dev_tools.dev_graph`` consumed by `nav_smoke.py --graph`).
"""
