"""
Vendor Alas modules into vendor/alas/ with import rewriting.

Reads Alas source from `_tmp_alas/` (sparse-checkout output) and writes
recursively-resolved modules into `vendor/alas/`. Only mutation is the
import-prefix rewrite (module.x -> vendor.alas.module.x). Logic is untouched.

Run from project root:
    python dev_tools/vendor_alas.py --root nemu_ipc

The --root flag names the seed module relative to module.device.method
(default: nemu_ipc, i.e. module.device.method.nemu_ipc).
"""

import argparse
import ast
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "_tmp_alas"
DST_ROOT = PROJECT_ROOT / "vendor" / "alas"

# Top-level Alas namespaces we vendor under vendor/alas/<ns>/...
# Each maps old prefix -> new prefix for import rewriting.
NAMESPACES = {
    "module": "vendor.alas.module",
    "deploy": "vendor.alas.deploy",
}


def find_source(dotted: str) -> Path | None:
    """Resolve `module.x.y` to a .py file path inside _tmp_alas/."""
    parts = dotted.split(".")
    candidate_file = SRC_ROOT.joinpath(*parts).with_suffix(".py")
    if candidate_file.is_file():
        return candidate_file
    candidate_pkg = SRC_ROOT.joinpath(*parts) / "__init__.py"
    if candidate_pkg.is_file():
        return candidate_pkg
    return None


def _in_namespace(dotted: str) -> bool:
    return any(dotted == ns or dotted.startswith(ns + ".") for ns in NAMESPACES)


def collect_module_imports(source: str) -> set[str]:
    """Return the set of `<ns>.*` dotted names imported by `source` for any vendored ns."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _in_namespace(alias.name):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            mod = node.module or ""
            if _in_namespace(mod):
                found.add(mod)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    found.add(f"{mod}.{alias.name}")
    return found


def rewrite_imports(source: str) -> str:
    """Rewrite `from <ns>.x import y` -> `from <new-prefix>.x import y` for every namespace."""
    out_lines = []
    for line in source.splitlines(keepends=True):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        replaced = False
        for old, new in NAMESPACES.items():
            if stripped.startswith(f"from {old}.") or stripped.startswith(f"from {old} "):
                out_lines.append(indent + stripped.replace(f"from {old}", f"from {new}", 1))
                replaced = True
                break
            if stripped.startswith(f"import {old}.") or stripped.startswith(f"import {old} "):
                out_lines.append(indent + stripped.replace(f"import {old}", f"import {new}", 1))
                replaced = True
                break
        if not replaced:
            out_lines.append(line)
    return "".join(out_lines)


def ensure_package_inits(dst: Path) -> None:
    """Create __init__.py up the directory chain inside vendor/alas/."""
    cur = dst.parent
    while cur != DST_ROOT and DST_ROOT in cur.parents or cur == DST_ROOT:
        init = cur / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")
        if cur == DST_ROOT:
            break
        cur = cur.parent


def copy_one(src: Path) -> Path:
    """Copy a source file to its mirrored location under vendor/alas/, rewriting imports."""
    rel = src.relative_to(SRC_ROOT)
    dst = DST_ROOT / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    ensure_package_inits(dst)
    text = src.read_text(encoding="utf-8")
    dst.write_text(rewrite_imports(text), encoding="utf-8")
    return dst


def resolve_and_copy(seed_dotted: str, log) -> None:
    seen_files: set[Path] = set()
    queue: list[str] = [seed_dotted]
    missing: set[str] = set()

    while queue:
        dotted = queue.pop()
        src = find_source(dotted)
        if src is None:
            # Could be a name imported from a parent package (e.g. `module.x.SomeClass`
            # where module.x is a file). Try the parent.
            parent = ".".join(dotted.split(".")[:-1])
            if parent and parent not in NAMESPACES:
                src = find_source(parent)
            if src is None:
                missing.add(dotted)
                continue
        if src in seen_files:
            continue
        seen_files.add(src)

        dst = copy_one(src)
        log(f"  + {src.relative_to(SRC_ROOT)}  ->  vendor/alas/{src.relative_to(SRC_ROOT)}")

        # Recurse on its imports
        source_text = src.read_text(encoding="utf-8")
        for dep in collect_module_imports(source_text):
            queue.append(dep)

    if missing:
        log("")
        log("Unresolved imports (names inside packages, usually fine — recorded for review):")
        for m in sorted(missing):
            log(f"  ? {m}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Vendor Alas modules with import rewriting.")
    parser.add_argument(
        "--root",
        default="nemu_ipc",
        help="Seed module under module.device.method (default: nemu_ipc).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe vendor/alas/module/ before copying.",
    )
    args = parser.parse_args()

    if not SRC_ROOT.exists():
        print(f"FATAL: {SRC_ROOT} not found. Run sparse-checkout of Alas first.", file=sys.stderr)
        return 2

    if args.clean:
        mod_dir = DST_ROOT / "module"
        if mod_dir.exists():
            shutil.rmtree(mod_dir)
            print(f"Cleaned {mod_dir}")

    DST_ROOT.mkdir(parents=True, exist_ok=True)
    (DST_ROOT / "__init__.py").write_text("", encoding="utf-8")

    seed = f"module.device.method.{args.root}"
    print(f"Vendoring seed: {seed}")
    print(f"  src: {SRC_ROOT}")
    print(f"  dst: {DST_ROOT}")
    print()

    log_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    resolve_and_copy(seed, log)

    report = DST_ROOT / "_vendor_report.txt"
    report.write_text("\n".join(log_lines), encoding="utf-8")
    print()
    print(f"Vendor report written to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
