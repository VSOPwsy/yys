"""
Vision debug — visualize a template match.

Loads a saved screenshot + a template name, runs `TemplateMatcher.find` /
`find_all`, and renders the match boxes on the screenshot for inspection.
Used to tune `Button.threshold` and `Button.region`.

Developer-only tool (CLAUDE.md S3).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.logging_config import setup_logging  # noqa: E402
from core.vision.button import Button  # noqa: E402
from core.vision.template_matcher import TemplateMatcher  # noqa: E402
from core.vision.template_repository import TemplateRepository  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--screenshot", required=True, help="Path to a captured screenshot (PNG/JPG).")
    p.add_argument("--template", required=True, help="Template logical name, e.g. main_menu/profile_btn")
    p.add_argument("--threshold", type=float, default=0.85)
    p.add_argument(
        "--region",
        nargs=4,
        type=int,
        metavar=("X1", "Y1", "X2", "Y2"),
        default=None,
        help="Search region in ADB coords.",
    )
    p.add_argument("--all", action="store_true", help="Show every match, not just the best.")
    p.add_argument("--out", default=None, help="Save annotated PNG to this path instead of showing it.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging()

    screenshot = cv2.imread(args.screenshot, cv2.IMREAD_COLOR)
    if screenshot is None:
        print(f"FATAL: could not load screenshot at {args.screenshot}", file=sys.stderr)
        return 2

    repo = TemplateRepository()
    matcher = TemplateMatcher(repo)

    button = Button(
        template=args.template,
        threshold=args.threshold,
        region=tuple(args.region) if args.region else None,
    )
    annotated = screenshot.copy()

    template = repo.get(args.template)
    h, w = template.shape[:2]

    points = matcher.find_all(screenshot, button) if args.all else (
        [pt] if (pt := matcher.find(screenshot, button)) else []
    )

    for (cx, cy) in points:
        x1 = cx - w // 2
        y1 = cy - h // 2
        cv2.rectangle(annotated, (x1, y1), (x1 + w, y1 + h), (0, 255, 0), 2)
        cv2.circle(annotated, (cx, cy), 4, (0, 0, 255), -1)

    if button.region is not None:
        rx1, ry1, rx2, ry2 = button.region
        cv2.rectangle(annotated, (rx1, ry1), (rx2, ry2), (255, 0, 0), 1)

    label = f"{args.template}  threshold={args.threshold}  matches={len(points)}"
    cv2.putText(annotated, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    print(label)

    if args.out:
        if not cv2.imwrite(args.out, annotated):
            print(f"FATAL: cv2.imwrite failed for {args.out}", file=sys.stderr)
            return 3
        print(f"wrote {args.out}")
    else:
        cv2.imshow("vision_debug", annotated)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
