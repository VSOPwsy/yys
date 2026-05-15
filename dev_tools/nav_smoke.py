"""
Navigation smoke test — drive Navigator on a real emulator without a plugin.

Use this whenever you've just added a vertex / edge / template and want to
prove the wiring works end-to-end before building a full plugin:

* the assembled graph actually contains the new vertex,
* `ScreenRecognizer` recognizes the live screen as the expected start vertex,
* `PathFinder` finds a path from current → target,
* each edge's `action` (click_button, swipe, wait, ...) executes without
  exception,
* after each edge, the destination vertex is recognized — i.e. the click
  template hit the right pixel and the game responded.

Two modes:
    --dry-run     Detect current, print the path, do not execute. Use this
                  to confirm wiring before risking taps on the live game.
    (default)     Actually invoke Navigator.goto(target).

Per CLAUDE.md S3, dev-only: never imported by core / plugins / main.py.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.exceptions import NavigationError  # noqa: E402
from core.input_backend.factory import get_input_backend  # noqa: E402
from core.logging_config import get_logger, setup_logging  # noqa: E402
from core.navigation import (  # noqa: E402
    Navigator,
    PathFinder,
    ScreenRecognizer,
)
from core.vision.button import Button  # noqa: E402

log = get_logger(__name__)


def _install_verbose_click_log(backend) -> None:
    """Monkey-patch backend so every `click(Button)` logs at INFO level.

    Three pieces are logged, enough to triangulate "did the script point
    at the right pixel" against MuMu's "Show touches" overlay:

      * `click=` final coordinate sent to ``click_xy`` (after bbox-jitter).
      * `match=` the ``(cx, cy)`` returned by `TemplateMatcher.find` —
        the geometric click center *before* jitter. Big gap between this
        and `click=` means jitter pushed the tap far from the match.
      * `bbox=` corners of the matched template rectangle, plus its size.
        Compare against where the button visually sits on screen.

    Implemented by patching `matcher.find` (to capture the last result per
    template) and `backend.click` (to read the captured result after the
    real click runs). No double screenshot — we read the side effect of
    `click()`'s own match call.
    """
    matcher = backend.matcher
    original_find = matcher.find
    original_click = backend.click
    last_finds: dict[str, tuple[int, int] | None] = {}

    def find_save(screenshot, button):
        result = original_find(screenshot, button)
        last_finds[button.template] = result
        return result

    matcher.find = find_save  # type: ignore[assignment]

    def click_log(target, *, post_delay=None, randomize=True):
        result = original_click(target, post_delay=post_delay, randomize=randomize)
        if not isinstance(target, Button):
            log.info("[click] raw=(%d,%d)", result[0], result[1])
            return result

        match = last_finds.get(target.template)
        bbox_str = ""
        try:
            template = matcher.repository.get(target.template)
            h, w = template.shape[:2]
            if match is not None:
                # The bbox is centered on the geometric match center, which
                # is `match` minus the configured click_offset (matcher.find
                # already applied it).
                ox, oy = target.click_offset
                cx_geo = match[0] - ox
                cy_geo = match[1] - oy
                x1, y1 = cx_geo - w // 2, cy_geo - h // 2
                bbox_str = f"  bbox=({x1},{y1})-({x1 + w},{y1 + h}) {w}x{h}"
        except Exception:  # noqa: BLE001
            # Template may not be loadable in pathological cases; don't
            # break the click logging just because the bbox tag is missing.
            pass

        if match is not None:
            jx = result[0] - match[0]
            jy = result[1] - match[1]
            log.info(
                "[click] %s  click=(%d,%d)  match=(%d,%d)  jitter=(%+d,%+d)%s",
                target.display_name, result[0], result[1],
                match[0], match[1], jx, jy, bbox_str,
            )
        else:
            # click() succeeded but the cached find result is missing —
            # shouldn't happen because click(Button) calls find() itself,
            # but be defensive in case someone wraps click() differently.
            log.info(
                "[click] %s  click=(%d,%d)  match=?  (cached find missing)%s",
                target.display_name, result[0], result[1], bbox_str,
            )
        return result

    backend.click = click_log  # type: ignore[assignment]


def _build_graph(spec: str):
    """Resolve `module:callable` into a GameGraph (no args)."""
    if ":" not in spec:
        raise ValueError(f"--graph expects 'module:callable', got {spec!r}")
    mod_name, fn_name = spec.split(":", 1)
    return getattr(importlib.import_module(mod_name), fn_name)()


def _action_name(action) -> str:
    """Best-effort label for an edge action (for the dry-run printout)."""
    for attr in ("__name__", "__qualname__"):
        if hasattr(action, attr):
            return getattr(action, attr)
    return type(action).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mumu", required=True,
                        help="MuMu 12 install root.")
    parser.add_argument("--instance", type=int, default=0)
    parser.add_argument("--display", type=int, default=0)
    parser.add_argument("--account-id", default="nav_smoke")
    parser.add_argument("--graph", default="graphs.main:build_main_graph",
                        help="module:callable returning a GameGraph "
                             "(default: graphs.main:build_main_graph).")
    parser.add_argument("--target", required=True,
                        help="Vertex id to navigate to, e.g. 'tingyuanshiwu' "
                             "or 'daily_reward.sign_in_panel'.")
    parser.add_argument("--mode", default="shortest",
                        choices=["shortest", "random"],
                        help="PathFinder mode.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect current vertex + print path, do NOT click.")
    parser.add_argument("--verbose-clicks", action="store_true",
                        help="INFO-level log every Button click with "
                             "click point, match center, jitter offset, and "
                             "bbox bounds. Compare against MuMu's "
                             "'Show touches' to diagnose off-target clicks.")
    parser.add_argument("--no-humanize", action="store_true",
                        help="Disable click jitter + post-delay variance. "
                             "Clicks land exactly on the match center, "
                             "post-delay is exact. Use only to repro a "
                             "specific click-offset bug — otherwise dev "
                             "tools should mirror production humanization "
                             "(default behavior).")
    args = parser.parse_args()
    setup_logging(account_id=args.account_id)

    graph = _build_graph(args.graph)

    # Run validate() up front so dangling cross-namespace edges (e.g. an
    # edge pointing at "foo.bar" when only "bar" was registered) get logged
    # *here* rather than silently miss during shortest_path. assemble()
    # would do this in production; we mirror that.
    dropped = graph.validate()
    if dropped:
        log.warning("validate() dropped %d dangling edge(s) — likely typos "
                    "in edge() targets:", len(dropped))
        for e in dropped:
            log.warning("  %s -> %s", e.src, e.dst)

    vertices = list(graph.vertex_ids())
    log.info("loaded %s — %d vertices, %d edges",
             args.graph, len(vertices), sum(1 for _ in graph.edges()))

    if args.target not in vertices:
        log.error("target vertex %r not in graph. registered: %s",
                  args.target, sorted(vertices))
        return 2

    # Mirror production humanization knobs. main.py sources these from
    # config.yaml's `global.humanize` section; here we use HumanizeConfig
    # defaults so dev tool behavior matches what plugins will experience
    # in production. Without this, `_jitter_radius is None` and every
    # `click(Button)` lands on the exact match center — operators
    # watching MuMu's "Show touches" see suspiciously identical pixels
    # frame to frame, which is exactly what humanization is supposed to
    # prevent. `--no-humanize` toggles this off for the rare case you
    # need pixel-deterministic clicks to repro a specific bug.
    # Throttle stays off in dev tools — slowing down a smoke test by
    # max_actions_per_minute is annoying and not what we're verifying.
    from core.config import HumanizeConfig
    humanize = HumanizeConfig()
    backend = get_input_backend(
        account_id=args.account_id,
        backend_name="nemu",
        mumu_folder=args.mumu,
        instance_id=args.instance,
        display_id=args.display,
        jitter_radius=None if args.no_humanize else humanize.click_jitter_radius,
        post_delay_variance=0.0 if args.no_humanize else humanize.post_delay_variance,
        bbox_margin=humanize.bbox_margin,
    )
    if args.verbose_clicks:
        _install_verbose_click_log(backend)

    with backend:
        recognizer = ScreenRecognizer(matcher=backend.matcher)
        shot = backend.screenshot()
        current = recognizer.detect_current(shot, graph)
        if current is None:
            log.error(
                "could not recognize current vertex from live screen. "
                "Hints: (1) is the right screen actually showing? "
                "(2) is the anchor template captured + threshold sensible? "
                "Use dev_tools/screen_inspector.py to debug interactively."
            )
            return 3
        log.info("current vertex: %s", current)

        if current == args.target:
            log.info("already at %s — nothing to do", args.target)
            return 0

        try:
            path = PathFinder(graph).shortest_path(current, args.target)
        except NavigationError as exc:
            log.error("no path %s -> %s: %s", current, args.target, exc)
            return 4

        log.info("path (%d edges):", len(path))
        for i, e in enumerate(path, 1):
            risky = " [risky]" if e.risky else ""
            tags = f" tags={e.tags}" if e.tags else ""
            log.info("  %d. %s -> %s  via %s  cost=%.2f%s%s",
                     i, e.src, e.dst, _action_name(e.action),
                     e.cost, risky, tags)

        if args.dry_run:
            log.info("--dry-run: not executing. Re-run without --dry-run to actually click.")
            return 0

        log.info("invoking Navigator.goto(%r, mode=%s) ...", args.target, args.mode)
        nav = Navigator(backend, graph)
        t0 = time.monotonic()
        try:
            ok = nav.goto(args.target, mode=args.mode)
        except NavigationError as exc:
            log.error("Navigator.goto raised NavigationError: %s", exc)
            return 5
        except Exception:
            log.exception("Navigator.goto raised unexpected exception")
            return 6
        elapsed = time.monotonic() - t0

        if ok:
            log.info("OK — arrived at %s in %.2fs", args.target, elapsed)
            return 0
        log.error("Navigator.goto returned False after %.2fs "
                  "(replans exhausted; check logs above for which edge failed)",
                  elapsed)
        return 7


if __name__ == "__main__":
    raise SystemExit(main())
