"""Probe vendor/alas/ for 3rd-party imports we need to install."""
import ast
import sys
from pathlib import Path

STDLIB = set(sys.stdlib_module_names) | {"__future__"}
LOCAL_PREFIXES = ("vendor", "core", "plugins", "graphs")

root = Path(__file__).resolve().parent.parent / "vendor" / "alas"
externals: set[str] = set()

for py in root.rglob("*.py"):
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                externals.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            mod = node.module or ""
            top = mod.split(".")[0]
            externals.add(top)

externals = {x for x in externals if x and x not in STDLIB and not x.startswith(LOCAL_PREFIXES)}
for x in sorted(externals):
    print(x)
