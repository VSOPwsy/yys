"""
Template extractor — interactive tool for capturing UI templates.

Workflow:
    1. Launch with an emulator already running.
    2. A live screenshot opens in an OpenCV window.
    3. Click-drag to select a region.
    4. Press ``C`` to crop the selection.
    5. Type a logical name (e.g. ``main_menu/profile_button``) in the
       terminal and press Enter -> saved to ``templates/<name>.png``.
    6. Press ``S`` to grab a fresh screenshot.
    7. Press ``A`` after cropping to toggle "alpha mode": you pick a
       background color with a left click, similar pixels become
       transparent (good for buttons over a complex background).
    8. Press ``Q`` to quit.

This is a developer-only tool. Per CLAUDE.md S3, production code must NOT
import this module.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.input_backend.factory import get_input_backend  # noqa: E402
from core.logging_config import setup_logging  # noqa: E402

TEMPLATES_ROOT = PROJECT_ROOT / "templates"
WINDOW_NAME = "template_extractor (drag=select, S=shot, C=crop, A=alpha, Q=quit)"


class _State:
    def __init__(self) -> None:
        self.screenshot: Optional[np.ndarray] = None
        self.display: Optional[np.ndarray] = None
        self.selecting: bool = False
        self.start: Optional[Tuple[int, int]] = None
        self.end: Optional[Tuple[int, int]] = None
        self.crop: Optional[np.ndarray] = None  # last cropped sub-image (BGR)
        self.alpha_mode: bool = False
        self.alpha_pick: Optional[Tuple[int, int, int]] = None
        self.alpha_tolerance: int = 25


def _on_mouse(event: int, x: int, y: int, flags: int, state: _State) -> None:
    if event == cv2.EVENT_LBUTTONDOWN:
        if state.alpha_mode and state.crop is not None:
            # In alpha mode the click samples a background color in the crop
            # preview window (separate window, handled below).
            return
        state.selecting = True
        state.start = (x, y)
        state.end = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and state.selecting:
        state.end = (x, y)
    elif event == cv2.EVENT_LBUTTONUP and state.selecting:
        state.selecting = False
        state.end = (x, y)


def _on_crop_click(event: int, x: int, y: int, flags: int, state: _State) -> None:
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    if state.crop is None:
        return
    b, g, r = state.crop[y, x][:3].tolist()
    state.alpha_pick = (int(b), int(g), int(r))


def _render(state: _State) -> Optional[np.ndarray]:
    if state.screenshot is None:
        return None
    canvas = state.screenshot.copy()
    if state.start and state.end:
        x1, y1 = state.start
        x2, y2 = state.end
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)
    return canvas


def _normalize_rect(
    p1: Tuple[int, int], p2: Tuple[int, int], shape: Tuple[int, ...]
) -> Tuple[int, int, int, int]:
    h, w = shape[:2]
    x1, y1 = p1
    x2, y2 = p2
    x1, x2 = sorted((max(0, min(w, x1)), max(0, min(w, x2))))
    y1, y2 = sorted((max(0, min(h, y1)), max(0, min(h, y2))))
    return x1, y1, x2, y2


def _apply_alpha(crop_bgr: np.ndarray, picked: Tuple[int, int, int], tol: int) -> np.ndarray:
    """Convert BGR crop to BGRA with pixels near `picked` made transparent."""
    bgra = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2BGRA)
    diff = np.abs(crop_bgr.astype(np.int16) - np.array(picked, dtype=np.int16))
    mask = np.all(diff <= tol, axis=2)
    bgra[mask, 3] = 0
    return bgra


def _prompt_name() -> Optional[str]:
    try:
        raw = input("template name (e.g. main_menu/profile_button) [empty=cancel]: ")
    except EOFError:
        return None
    raw = raw.strip().strip("/").replace("\\", "/")
    if not raw:
        return None
    if raw.lower().endswith(".png"):
        raw = raw[:-4]
    return raw


def _save(name: str, image: np.ndarray) -> Path:
    path = TEMPLATES_ROOT.joinpath(*name.split("/")).with_suffix(".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"cv2.imwrite failed for {path}")
    return path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mumu", required=True, help="MuMu 12 install root")
    p.add_argument("--instance", type=int, default=0)
    p.add_argument("--display", type=int, default=0)
    p.add_argument("--account-id", default="dev")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging()

    backend = get_input_backend(
        account_id=args.account_id,
        backend_name="nemu",
        mumu_folder=args.mumu,
        instance_id=args.instance,
        display_id=args.display,
    )
    backend.connect()

    state = _State()
    state.screenshot = backend.screenshot()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW_NAME, _on_mouse, state)

    crop_window = "crop_preview"

    print("ready. drag a rectangle on the screenshot.")

    try:
        while True:
            canvas = _render(state)
            if canvas is not None:
                cv2.imshow(WINDOW_NAME, canvas)

            if state.crop is not None:
                preview = state.crop
                if state.alpha_mode and state.alpha_pick is not None:
                    preview = _apply_alpha(state.crop, state.alpha_pick, state.alpha_tolerance)
                cv2.imshow(crop_window, preview)
                cv2.setMouseCallback(crop_window, _on_crop_click, state)

            key = cv2.waitKey(20) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                state.screenshot = backend.screenshot()
                state.start = state.end = None
                state.crop = None
                state.alpha_mode = False
                state.alpha_pick = None
                print("re-captured.")
            elif key == ord("c"):
                if state.start is None or state.end is None or state.screenshot is None:
                    print("nothing selected.")
                    continue
                x1, y1, x2, y2 = _normalize_rect(state.start, state.end, state.screenshot.shape)
                if x2 - x1 < 4 or y2 - y1 < 4:
                    print("selection too small.")
                    continue
                state.crop = state.screenshot[y1:y2, x1:x2].copy()
                state.alpha_mode = False
                state.alpha_pick = None
                print(f"cropped region: ({x1},{y1})-({x2},{y2}) shape={state.crop.shape}")
                name = _prompt_name()
                if name is None:
                    print("save cancelled.")
                    continue
                saved = _save(name, state.crop)
                print(f"saved BGR -> {saved}")
            elif key == ord("a"):
                if state.crop is None:
                    print("crop first (C) before toggling alpha mode.")
                    continue
                state.alpha_mode = not state.alpha_mode
                print(
                    f"alpha mode {'ON — click on background color in preview' if state.alpha_mode else 'OFF'}"
                )
                if not state.alpha_mode:
                    state.alpha_pick = None
            elif key == ord("w") and state.alpha_mode and state.alpha_pick is not None and state.crop is not None:
                bgra = _apply_alpha(state.crop, state.alpha_pick, state.alpha_tolerance)
                name = _prompt_name()
                if name is None:
                    print("save cancelled.")
                    continue
                saved = _save(name, bgra)
                print(f"saved BGRA -> {saved}")
            elif key == ord("+"):
                state.alpha_tolerance = min(state.alpha_tolerance + 5, 100)
                print(f"tolerance={state.alpha_tolerance}")
            elif key == ord("-"):
                state.alpha_tolerance = max(state.alpha_tolerance - 5, 0)
                print(f"tolerance={state.alpha_tolerance}")

            time.sleep(0.005)
    finally:
        cv2.destroyAllWindows()
        backend.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
