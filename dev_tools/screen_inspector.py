"""
Live recognition inspector for tuning vertex recognizers.

Pulls one frame from a real `NemuIpcBackend`, runs `ScreenRecognizer`
against an assembled graph, and prints which vertex (if any) was detected.
Press R in the OpenCV window to refresh; Q to quit.

Why a static snapshot rather than a video loop
----------------------------------------------
nemu IPC screenshots cost ~50ms each on this machine and pin a CPU core if
you grab them at video rate. Tuning recognizers is also fundamentally a
"freeze a frame, eyeball it, adjust thresholds, refresh" workflow — a
video stream would just smear the operator's attention.

Per CLAUDE.md S3, this file is dev-only and must not be imported by `core/`
or production code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402

from core.input_backend.factory import get_input_backend  # noqa: E402
from core.logging_config import setup_logging, get_logger  # noqa: E402
from core.navigation import GraphAssembler, ScreenRecognizer  # noqa: E402

log = get_logger(__name__)


def _build_graph(spec: str | None):
    """Resolve the graph to inspect.

    With no spec: assemble the Phase 2 demo graph (root + `_demo`).
    With `module:fn` spec: import and call it; expects a `GameGraph` back.
    """
    if spec is None:
        from graphs._demo import build_main_graph
        from plugins._demo.graph import build_subgraph
        asm = GraphAssembler()
        asm.set_main(build_main_graph())
        asm.add_subgraph("_demo", build_subgraph())
        return asm.assemble()

    if ":" not in spec:
        raise ValueError(f"--graph expects 'module:callable', got {spec!r}")
    import importlib
    mod_name, fn_name = spec.split(":", 1)
    return getattr(importlib.import_module(mod_name), fn_name)()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mumu", required=True,
                        help="MuMu 12 install root (contains shell/, nx_device/, ...).")
    parser.add_argument("--instance", type=int, default=0,
                        help="MuMu instance id.")
    parser.add_argument("--display", type=int, default=0,
                        help="MuMu display id.")
    parser.add_argument("--account-id", default="dev",
                        help="account_id for the backend.")
    parser.add_argument("--graph", default=None,
                        help="module:callable returning a GameGraph "
                             "(omit to use the demo graph).")
    args = parser.parse_args()
    setup_logging(account_id=args.account_id)

    graph = _build_graph(args.graph)
    log.info("inspecting %s", graph)

    backend = get_input_backend(
        account_id=args.account_id,
        backend_name="nemu",
        mumu_folder=args.mumu,
        instance_id=args.instance,
        display_id=args.display,
    )
    recognizer = ScreenRecognizer(matcher=backend.matcher)

    with backend:
        win = "screen_inspector"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 960, 540)

        while True:
            shot = backend.screenshot()
            vid = recognizer.detect_current(shot, graph)
            label = vid or "<unknown>"
            log.info("detected: %s", label)

            # Overlay the label on the bottom-left corner.
            preview = shot.copy()
            cv2.putText(
                preview,
                f"vertex: {label}",
                (24, preview.shape[0] - 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (0, 255, 0) if vid else (0, 0, 255),
                3,
                cv2.LINE_AA,
            )
            cv2.imshow(win, preview)

            key = cv2.waitKey(0) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("r"), ord("R")):
                continue
            # Any other key also refreshes (forgiving UX).

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
