"""
Phase 0 IPC smoke test.

Walks NemuIpcImpl through:
    connect -> screenshot -> save PNG -> down/up at (x,y) -> disconnect
and prints the wall-clock cost of each step.

Run from project root, e.g.:
    python dev_tools/ipc_smoke_test.py \
        --mumu "D:\\Program Files\\Netease\\MuMu" \
        --instance 0 \
        --xy 540 960

Notes:
- DLL screenshots come back BGRA + upside-down. We convert to BGR + flip
  before writing the PNG so it opens correctly in any viewer.
- DLL coordinates are rotated 90deg vs ADB; NemuIpcImpl.convert_xy handles
  this internally for down(), so we pass classic ADB (x,y).
- This script is a dev tool. Production code must not import it (see
  CLAUDE.md S 3 dev_tools isolation rule).
"""

import argparse
import os
import sys
import time
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vendor.alas.module.device.method.nemu_ipc import NemuIpcImpl  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke-test nemu_ipc end-to-end.")
    p.add_argument(
        "--mumu",
        required=True,
        help=r'MuMu 12 install folder, e.g. "D:\Program Files\Netease\MuMu"',
    )
    p.add_argument(
        "--instance",
        type=int,
        default=0,
        help="MuMu instance id (default 0).",
    )
    p.add_argument(
        "--display",
        type=int,
        default=0,
        help="Display id (default 0, only nonzero if keep-alive is on).",
    )
    p.add_argument(
        "--xy",
        nargs=2,
        type=int,
        metavar=("X", "Y"),
        default=None,
        help="ADB (x,y) to tap. Default: center of the screenshot.",
    )
    p.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "dev_tools" / "ipc_smoke_test.png"),
        help="PNG output path.",
    )
    p.add_argument(
        "--no-tap",
        action="store_true",
        help="Skip the down/up step (useful if you don't want to touch the UI).",
    )
    p.add_argument(
        "--bypass-rotation",
        action="store_true",
        help="Replace Alas's NemuIpcImpl.convert_xy with identity (no 90° "
             "rotation). Use this to verify whether your MuMu DLL needs the "
             "legacy ADB->portrait rotation. With this flag, the tap goes to "
             "the raw ADB (x,y); without it, Alas rotates first. Compare "
             "where MuMu's 'Show touches' draws the circle to decide which "
             "is correct for your install. See CLAUDE.md §7 'DLL 坐标系'.",
    )
    return p.parse_args()


class StepTimer:
    def __init__(self) -> None:
        self.results: list[tuple[str, float]] = []

    def step(self, label: str):
        timer = self
        class _Ctx:
            def __enter__(self_inner):
                self_inner.t0 = time.perf_counter()
                print(f"-> {label} ...", flush=True)
                return self_inner

            def __exit__(self_inner, exc_type, exc_val, exc_tb):
                dt = (time.perf_counter() - self_inner.t0) * 1000
                timer.results.append((label, dt))
                marker = "OK" if exc_type is None else "FAIL"
                print(f"   [{marker}] {label}  {dt:7.1f} ms", flush=True)
                return False
        return _Ctx()

    def report(self) -> None:
        print()
        print("=" * 48)
        print(f"{'Step':<28}{'ms':>10}")
        print("-" * 48)
        for label, dt in self.results:
            print(f"{label:<28}{dt:>10.1f}")
        print("=" * 48)
        print(f"{'TOTAL':<28}{sum(dt for _, dt in self.results):>10.1f}")


def main() -> int:
    args = parse_args()

    if not os.path.isdir(args.mumu):
        print(f"FATAL: --mumu path not found: {args.mumu}", file=sys.stderr)
        return 2

    timer = StepTimer()

    with timer.step("instantiate NemuIpcImpl"):
        ipc = NemuIpcImpl(
            nemu_folder=args.mumu,
            instance_id=args.instance,
            display_id=args.display,
        )

    if args.bypass_rotation:
        # Same patch NemuIpcBackend applies when it detects the v5.0+ DLL.
        # Doing it here too lets us isolate the rotation question at the
        # vendor layer (no backend / matcher / Button involved).
        ipc.convert_xy = lambda x, y: (int(x), int(y))
        print("   [bypass-rotation] convert_xy replaced with identity")

    with timer.step("connect"):
        ipc.connect()

    with timer.step("screenshot"):
        image = ipc.screenshot()

    with timer.step("post-process (BGRA->BGR + flip)"):
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        cv2.flip(image, 0, dst=image)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with timer.step(f"write PNG -> {out_path.name}"):
        ok = cv2.imwrite(str(out_path), image)
    if not ok:
        print(f"FATAL: cv2.imwrite returned False for {out_path}", file=sys.stderr)
        return 3
    print(f"   resolution: {ipc.width} x {ipc.height}")
    print(f"   saved: {out_path}")

    if not args.no_tap:
        if args.xy is None:
            x, y = ipc.width // 2, ipc.height // 2
        else:
            x, y = args.xy
        print(f"   tap target (ADB coords): ({x}, {y})")
        with timer.step("down"):
            ipc.down(x, y)
        time.sleep(0.02)
        with timer.step("up"):
            ipc.up()

    with timer.step("disconnect"):
        ipc.disconnect()

    timer.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
