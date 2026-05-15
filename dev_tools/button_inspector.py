"""
Button inspector — live verification that a captured template clicks the
right thing on the screen.

Where the other tools fall short for this job
---------------------------------------------
* ``screen_inspector.py`` only answers "which vertex am I on", which uses
  *anchors*. It does not draw a match box for an arbitrary action button
  and does not show match scores.
* ``vision_debug.py`` does draw a match box and computes scores, but it
  needs you to first save a screenshot to disk by hand, and it cannot load
  the production ``Button`` object (you'd lose the real ``threshold`` /
  ``region`` / ``click_offset`` configured in code).

This tool pulls a live frame from the emulator and renders, on top:
* The match bounding box (green) and click center (red dot).
* The configured search region (blue) if any.
* A status overlay with the score, headroom over threshold, match count.
* A verdict banner: PASS / MARGINAL / AMBIGUOUS / FAIL.

Live tunable, no save-screenshot dance.

Per CLAUDE.md S3, this file is dev-only and must NOT be imported by
``core/``, ``plugins/`` or ``main.py``.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from core.input_backend.factory import get_input_backend  # noqa: E402
from core.logging_config import get_logger, setup_logging  # noqa: E402
from core.vision.button import Button  # noqa: E402
from core.vision.template_repository import TemplateRepository  # noqa: E402

log = get_logger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent / "button_inspector_out"
WINDOW = "button_inspector (R=refresh A=all +/- threshold S=save Q=quit)"

# Verdict colors (BGR).
COLOR_PASS = (40, 200, 80)
COLOR_MARGINAL = (40, 200, 220)
COLOR_AMBIGUOUS = (40, 130, 240)
COLOR_FAIL = (60, 60, 230)

# Per-match overlay colors.
COLOR_BOX = (0, 255, 0)
COLOR_CENTER = (0, 0, 255)
COLOR_REGION = (255, 80, 0)
COLOR_TEXT = (0, 255, 255)
COLOR_TEXT_BG = (0, 0, 0)


# ---------------------------------------------------------------- match core


@dataclass
class Match:
    """One result of running ``cv2.matchTemplate`` on the live frame."""

    box: Tuple[int, int, int, int]  # (x1, y1, x2, y2) in screenshot coords
    click: Tuple[int, int]           # click point with click_offset applied
    score: float                     # raw matchTemplate score, [-1, 1]


def _split_alpha(template: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Mirror what ``TemplateMatcher._prep_template`` does for BGRA inputs."""
    if template.ndim == 3 and template.shape[2] == 4:
        return template[..., :3].copy(), template[..., 3].copy()
    return template, None


def _run_match(
    screenshot: np.ndarray,
    template: np.ndarray,
    button: Button,
    find_all: bool,
) -> List[Match]:
    """Run cv2.matchTemplate honoring ``button.region``/``threshold``/etc.

    Re-implemented (vs. calling ``TemplateMatcher.find``) so the *raw score*
    is available for display — the production matcher only returns a click
    point on success.
    """
    bgr, mask = _split_alpha(template)
    th, tw = bgr.shape[:2]
    dx, dy = button.click_offset

    if button.region is not None:
        x1, y1, x2, y2 = button.region
        h, w = screenshot.shape[:2]
        x1 = max(0, min(w, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(0, min(h, y2))
        crop = screenshot[y1:y2, x1:x2]
        ox, oy = x1, y1
    else:
        crop = screenshot
        ox, oy = 0, 0

    if crop.shape[0] < th or crop.shape[1] < tw:
        log.warning("search region (%dx%d) smaller than template (%dx%d)",
                    crop.shape[1], crop.shape[0], tw, th)
        return []

    result = cv2.matchTemplate(crop, bgr, cv2.TM_CCOEFF_NORMED, mask=mask)

    if not find_all:
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if not np.isfinite(max_val) or max_val < button.threshold:
            return []
        x, y = max_loc
        return [_make_match(x + ox, y + oy, th, tw, dx, dy, float(max_val))]

    ys, xs = np.where(result >= button.threshold)
    merge_radius = max(tw, th) // 2
    accepted: List[Tuple[int, int, float]] = []
    for x, y in zip(xs.tolist(), ys.tolist()):
        score = float(result[y, x])
        if not np.isfinite(score):
            continue
        if any(abs(x - ax) <= merge_radius and abs(y - ay) <= merge_radius
               for ax, ay, _ in accepted):
            continue
        accepted.append((x, y, score))
    accepted.sort(key=lambda t: -t[2])  # highest score first
    return [
        _make_match(x + ox, y + oy, th, tw, dx, dy, score)
        for x, y, score in accepted
    ]


def _make_match(x: int, y: int, th: int, tw: int, dx: int, dy: int,
                score: float) -> Match:
    cx = x + tw // 2 + dx
    cy = y + th // 2 + dy
    return Match(box=(x, y, x + tw, y + th), click=(cx, cy), score=score)


# ----------------------------------------------------------------- rendering


def _put_text(img: np.ndarray, text: str, org: Tuple[int, int],
              scale: float = 0.55, color=COLOR_TEXT, thickness: int = 1) -> None:
    """Draw text with a black filled background for readability."""
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    x, y = org
    cv2.rectangle(img, (x - 3, y - th - 4), (x + tw + 3, y + base + 2),
                  COLOR_TEXT_BG, -1)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, thickness, cv2.LINE_AA)


def _verdict(matches: List[Match], threshold: float) -> Tuple[str, Tuple[int, int, int]]:
    """Compress (count, top score) into PASS/MARGINAL/AMBIGUOUS/FAIL."""
    if not matches:
        return "FAIL — no match above threshold", COLOR_FAIL
    if len(matches) > 1:
        return f"AMBIGUOUS — {len(matches)} matches", COLOR_AMBIGUOUS
    top = matches[0].score
    headroom = top - threshold
    if headroom < 0.05:
        return f"MARGINAL — score {top:.3f}, only +{headroom:.3f} over threshold", COLOR_MARGINAL
    return f"PASS — score {top:.3f}, +{headroom:.3f} headroom", COLOR_PASS


def _render(
    screenshot: np.ndarray,
    button: Button,
    template_shape: Tuple[int, int],
    matches: List[Match],
    find_all: bool,
    live_threshold: float,
) -> np.ndarray:
    canvas = screenshot.copy()

    if button.region is not None:
        rx1, ry1, rx2, ry2 = button.region
        cv2.rectangle(canvas, (rx1, ry1), (rx2, ry2), COLOR_REGION, 1)
        _put_text(canvas, f"region {button.region}", (rx1, max(20, ry1 - 6)),
                  scale=0.5, color=COLOR_REGION)

    for i, m in enumerate(matches):
        x1, y1, x2, y2 = m.box
        cv2.rectangle(canvas, (x1, y1), (x2, y2), COLOR_BOX, 2)
        cv2.drawMarker(canvas, m.click, COLOR_CENTER,
                       markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)
        tag = f"#{i + 1} {m.score:.3f}" if find_all else f"{m.score:.3f}"
        _put_text(canvas, tag, (x1, max(20, y1 - 6)), scale=0.55)

    # Header overlay (top-left).
    lines = [
        f"template: {button.template}",
        f"threshold: {live_threshold:.3f}   mode: {'all' if find_all else 'best'}",
        f"matches: {len(matches)}"
        + (f"   top: {matches[0].score:.3f}" if matches else ""),
        f"click_offset: {button.click_offset}   tmpl_size: {template_shape[1]}x{template_shape[0]}",
        "[R]efresh  [A]ll-matches  [+/-] threshold  [S]ave  [Q]uit",
    ]
    for i, line in enumerate(lines):
        _put_text(canvas, line, (12, 24 + i * 22), scale=0.55)

    # Verdict banner (bottom-left).
    verdict_text, verdict_color = _verdict(matches, live_threshold)
    (tw, th), base = cv2.getTextSize(verdict_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    y_bot = canvas.shape[0] - 18
    cv2.rectangle(canvas, (12 - 6, y_bot - th - 8),
                  (12 + tw + 8, y_bot + base + 4), COLOR_TEXT_BG, -1)
    cv2.putText(canvas, verdict_text, (12, y_bot),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, verdict_color, 2, cv2.LINE_AA)

    return canvas


# --------------------------------------------------------------- button load


def _load_button_from_spec(spec: str) -> Button:
    if ":" not in spec:
        raise ValueError(f"--button expects 'module:VAR', got {spec!r}")
    mod_name, var = spec.split(":", 1)
    obj = getattr(importlib.import_module(mod_name), var)
    if not isinstance(obj, Button):
        raise TypeError(f"{spec} is {type(obj).__name__}, expected Button")
    return obj


def _resolve_button(args: argparse.Namespace) -> Button:
    if args.button:
        btn = _load_button_from_spec(args.button)
        # Allow CLI to override threshold / region (handy for live tuning).
        if args.threshold is not None or args.region is not None:
            btn = btn.with_(
                threshold=args.threshold if args.threshold is not None else btn.threshold,
                region=tuple(args.region) if args.region else btn.region,
            )
        return btn
    if not args.template:
        raise SystemExit("must pass either --button MOD:VAR or --template NAME")
    return Button(
        template=args.template,
        threshold=args.threshold if args.threshold is not None else 0.85,
        region=tuple(args.region) if args.region else None,
    )


# ------------------------------------------------------------------ CLI loop


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mumu", required=True,
                        help="MuMu 12 install root.")
    parser.add_argument("--instance", type=int, default=0)
    parser.add_argument("--display", type=int, default=0)
    parser.add_argument("--account-id", default="button_inspector")
    parser.add_argument("--button", default=None,
                        help="Production Button to inspect, e.g. "
                             "graphs.main_buttons:SIGN_IN_ENTRY_BTN")
    parser.add_argument("--template", default=None,
                        help="Raw template name (alternative to --button).")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Override Button.threshold for this session.")
    parser.add_argument(
        "--region", nargs=4, type=int,
        metavar=("X1", "Y1", "X2", "Y2"), default=None,
        help="Override Button.region (ADB coords).",
    )
    parser.add_argument("--all", action="store_true",
                        help="Start in find-all mode (toggle with A).")
    args = parser.parse_args()
    setup_logging(account_id=args.account_id)

    button = _resolve_button(args)
    repo = TemplateRepository()

    # Load the template once so render() can show its size in the overlay,
    # and so a missing-template error fires before we connect the emulator.
    template_img = repo.get(button.template)
    template_shape = template_img.shape[:2]

    log.info("inspecting button %s  template=%s  threshold=%.3f  region=%s",
             button.display_name, button.template, button.threshold, button.region)

    backend = get_input_backend(
        account_id=args.account_id,
        backend_name="nemu",
        mumu_folder=args.mumu,
        instance_id=args.instance,
        display_id=args.display,
    )

    find_all = bool(args.all)
    live_threshold = button.threshold

    with backend:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW, 960, 540)
        shot: Optional[np.ndarray] = None

        def refresh() -> None:
            nonlocal shot
            shot = backend.screenshot()

        refresh()

        while True:
            current = button.with_(threshold=live_threshold)
            # Reload template if it changed on disk (extractor re-saved it).
            try:
                template_now = repo.get(button.template)
                template_shape_now = template_now.shape[:2]
            except Exception as exc:  # noqa: BLE001
                log.error("template reload failed: %s", exc)
                template_now = template_img
                template_shape_now = template_shape

            matches = _run_match(shot, template_now, current, find_all)
            verdict_text, _ = _verdict(matches, live_threshold)
            log.info("%s  matches=%d  verdict=%s",
                     button.template, len(matches), verdict_text)

            canvas = _render(shot, current, template_shape_now,
                             matches, find_all, live_threshold)
            cv2.imshow(WINDOW, canvas)

            key = cv2.waitKey(0) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("r"), ord("R")):
                refresh()
                continue
            if key in (ord("a"), ord("A")):
                find_all = not find_all
                continue
            if key in (ord("+"), ord("=")):
                live_threshold = min(0.99, round(live_threshold + 0.02, 3))
                continue
            if key in (ord("-"), ord("_")):
                live_threshold = max(0.30, round(live_threshold - 0.02, 3))
                continue
            if key in (ord("i"), ord("I")):
                # Reload template cache and re-run (after re-extracting).
                repo.invalidate(button.template)
                continue
            if key in (ord("s"), ord("S")):
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                tag = button.template.replace("/", "_").replace("\\", "_")
                out = OUTPUT_DIR / f"{int(time.time())}_{tag}.png"
                if cv2.imwrite(str(out), canvas):
                    log.info("saved annotated frame to %s", out)
                else:
                    log.error("imwrite failed for %s", out)
                continue
            # Any other key: silently re-render (forgiving UX).

        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
