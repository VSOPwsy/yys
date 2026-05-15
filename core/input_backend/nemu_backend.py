"""
`NemuIpcBackend` — `InputBackend` over MuMu 12's nemu IPC DLL.

Owns lifecycle of a single `vendor.alas.module.device.method.nemu_ipc.NemuIpcImpl`
and translates its native exceptions into our own hierarchy.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from core.exceptions import BackendConnectionLost, BackendNotAvailable
from core.input_backend.base import InputBackend
from core.logging_config import get_logger
from core.vision.template_matcher import TemplateMatcher

if False:  # pragma: no cover — typing-only import
    from core.scheduler.throttle import Throttle

# NOTE: importing nemu_ipc transitively pulls in a slice of Alas runtime
# (logger, ConfigUpdater glue) — see CLAUDE.md S7 "vendor 依赖膨胀".
# Lazy-import inside the constructor to keep this module cheap to import.

log = get_logger(__name__)


class NemuIpcBackend(InputBackend):
    """Strategy implementation backed by MuMu 12's nemu IPC."""

    def __init__(
        self,
        account_id: str,
        mumu_folder: str,
        instance_id: int = 0,
        display_id: int = 0,
        matcher: Optional[TemplateMatcher] = None,
        *,
        throttle: "Optional[Throttle]" = None,
        jitter_radius: Optional[int] = None,
        post_delay_variance: float = 0.0,
        bbox_margin: float = 0.1,
    ) -> None:
        """Construct an unconnected backend bound to a MuMu instance.

        Constructor only loads the DLL. Network/IPC connection is deferred
        to `connect()` so the caller can decide when to pay that cost.

        Args:
            account_id: Per-account identity (see `InputBackend`).
            mumu_folder: MuMu 12 install **root** (the folder that contains
                ``shell/``, ``nx_device/``, ``vms/``...). NOT a subdirectory.
            instance_id: MuMu instance id, 0-based.
            display_id: MuMu display id; keep 0 unless background keep-alive
                is on (very uncommon in our workflow).
            matcher: Optional shared `TemplateMatcher`.

        Raises:
            BackendNotAvailable: `mumu_folder` is invalid, points at the
                Global edition, or the DLL is missing / too old.
        """
        super().__init__(
            account_id=account_id,
            matcher=matcher,
            throttle=throttle,
            jitter_radius=jitter_radius,
            post_delay_variance=post_delay_variance,
            bbox_margin=bbox_margin,
        )

        if "MuMuPlayerGlobal" in mumu_folder:
            raise BackendNotAvailable(
                "MuMuPlayerGlobal does not support nemu IPC. "
                "Use the Chinese MuMu 12 build."
            )
        if not os.path.isdir(mumu_folder):
            raise BackendNotAvailable(
                f"mumu_folder is not a directory: {mumu_folder!r}"
            )

        try:
            from vendor.alas.module.device.method.nemu_ipc import (
                NemuIpcImpl,
                NemuIpcError,
                NemuIpcIncompatible,
            )
        except ImportError as e:
            raise BackendNotAvailable(
                f"vendor.alas.module.device.method.nemu_ipc unavailable: {e}"
            ) from e

        self._NemuIpcError = NemuIpcError
        self._NemuIpcIncompatible = NemuIpcIncompatible

        try:
            self._ipc = NemuIpcImpl(
                nemu_folder=mumu_folder,
                instance_id=instance_id,
                display_id=display_id,
            )
        except NemuIpcIncompatible as e:
            raise BackendNotAvailable(str(e)) from e

        self._mumu_folder = mumu_folder
        self._instance_id = instance_id
        self._display_id = display_id

        # MuMu DLL coordinate-rotation bypass.
        #
        # `vendor/alas` ships a `NemuIpcImpl.convert_xy(x, y) = (height - y, x)`
        # — a 90° rotation from ADB-landscape into the DLL's portrait internal
        # coord. This is correct for *classic* MuMu 12 DLLs (the one at
        # `<root>/shell/sdk/external_renderer_ipc.dll`). The v5.0+ DLL at
        # `<root>/nx_device/12.0/shell/sdk/external_renderer_ipc.dll` accepts
        # ADB landscape coords directly; for that variant the rotation
        # actively breaks input — clicks land in the wrong quadrant.
        #
        # Detection mirrors Alas's loader (classic preferred when both exist),
        # so if classic is absent we know Alas loaded v5 and we must bypass
        # `convert_xy`. See CLAUDE.md §7 "MuMu DLL coord rotation".
        if self._needs_rotation_bypass(mumu_folder):
            self._ipc.convert_xy = lambda x, y: (int(x), int(y))
            self._log.info(
                "MuMu v5.0+ DLL detected; bypassing legacy convert_xy rotation "
                "(touches will use ADB landscape coords directly)"
            )
        # Serialize DLL access. The Alas wrapper already runs each DLL call
        # on a worker thread for timeout safety, but concurrent down/up from
        # multiple threads inside our process would still race the touch
        # state.
        self._call_lock = threading.RLock()
        self._connected = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        with self._call_lock:
            if self._connected:
                return
            try:
                self._ipc.connect()
            except self._NemuIpcIncompatible as e:
                raise BackendNotAvailable(str(e)) from e
            except self._NemuIpcError as e:
                raise BackendConnectionLost(str(e)) from e
            self._connected = True
            self._log.info(
                "nemu connected: account=%s instance=%d display=%d",
                self._account_id,
                self._instance_id,
                self._display_id,
            )

    def disconnect(self) -> None:
        with self._call_lock:
            if not self._connected:
                return
            try:
                self._ipc.disconnect()
            except self._NemuIpcError as e:
                # Disconnect errors aren't worth propagating — log and move on.
                self._log.warning("nemu disconnect raised: %s", e)
            finally:
                self._connected = False

    def is_connected(self) -> bool:
        return self._connected and getattr(self._ipc, "connect_id", 0) > 0

    # ------------------------------------------------------------------ #
    # Primitives
    # ------------------------------------------------------------------ #
    def screenshot(self) -> np.ndarray:
        try:
            with self._call_lock:
                raw = self._ipc.screenshot()
        except self._NemuIpcIncompatible as e:
            raise BackendNotAvailable(str(e)) from e
        except self._NemuIpcError as e:
            raise BackendConnectionLost(str(e)) from e
        except Exception as e:  # noqa: BLE001 — @retry can raise RequestHumanTakeover
            raise BackendConnectionLost(
                f"screenshot failed: {type(e).__name__}: {e}"
            ) from e
        # Mark as connected once we actually got a frame; NemuIpcImpl auto-connects.
        self._connected = self._connected or getattr(self._ipc, "connect_id", 0) > 0
        return self._postprocess(raw)

    def click_xy(self, x: int, y: int, randomize: bool = True) -> None:
        self._acquire_action_slot()
        tx, ty = (self._jitter(x, y) if randomize else (x, y))
        try:
            with self._call_lock:
                self._ipc.down(tx, ty)
                # short hold so the emulator registers a tap rather than a swipe
                time.sleep(0.02)
                self._ipc.up()
        except self._NemuIpcError as e:
            raise BackendConnectionLost(str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise BackendConnectionLost(
                f"click_xy({tx},{ty}) failed: {type(e).__name__}: {e}"
            ) from e

    def long_click_xy(self, x: int, y: int, duration: float) -> None:
        if duration <= 0:
            raise ValueError(f"duration must be > 0, got {duration}")
        self._acquire_action_slot()
        tx, ty = self._jitter(x, y) if duration < 1.5 else (x, y)
        try:
            with self._call_lock:
                self._ipc.down(tx, ty)
                time.sleep(duration)
                self._ipc.up()
        except self._NemuIpcError as e:
            raise BackendConnectionLost(str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise BackendConnectionLost(
                f"long_click_xy({tx},{ty},{duration}) failed: {type(e).__name__}: {e}"
            ) from e

    def swipe(
        self,
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        duration: float,
    ) -> None:
        if duration <= 0:
            raise ValueError(f"duration must be > 0, got {duration}")
        self._acquire_action_slot()
        # Swipe = fewer interpolation steps + minimal hold at the endpoint
        # = the emulator registers fling momentum.
        self._stroke(p1, p2, duration, steps=max(6, int(duration * 30)), hold_at_end=0.0)

    def drag(
        self,
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        duration: float,
    ) -> None:
        if duration <= 0:
            raise ValueError(f"duration must be > 0, got {duration}")
        self._acquire_action_slot()
        # Drag = many fine steps + small hold at endpoint so the emulator
        # interprets it as a controlled move, not a flick.
        self._stroke(
            p1, p2, duration, steps=max(20, int(duration * 60)), hold_at_end=0.08
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _postprocess(raw: np.ndarray) -> np.ndarray:
        """BGRA + upside-down -> BGR + upright.

        Mirrors `dev_tools/ipc_smoke_test.py`. Plugin code must see only the
        normalized form (CLAUDE.md S7 "DLL 截图格式").
        """
        bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        cv2.flip(bgr, 0, dst=bgr)
        return bgr

    @staticmethod
    def _needs_rotation_bypass(nemu_folder: str) -> bool:
        """True iff Alas will load the v5.0+ DLL, which doesn't need a
        90° rotation of input coords.

        Alas's `NemuIpcImpl.__init__` tries the classic path first and falls
        back to v5. We mirror that order: if the classic DLL exists, Alas
        will use it, and the legacy `convert_xy` rotation is correct; if only
        v5 is present, Alas loads v5 and `convert_xy` becomes wrong (clicks
        land in the wrong quadrant — diagnosed empirically by tapping a
        known ADB coord and watching MuMu's "Show touches" overlay).
        """
        classic = os.path.join(
            nemu_folder, "shell", "sdk", "external_renderer_ipc.dll"
        )
        v5 = os.path.join(
            nemu_folder, "nx_device", "12.0", "shell", "sdk",
            "external_renderer_ipc.dll",
        )
        return (not os.path.exists(classic)) and os.path.exists(v5)

    def _stroke(
        self,
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        duration: float,
        steps: int,
        hold_at_end: float,
    ) -> None:
        x1, y1 = p1
        x2, y2 = p2
        if steps < 2:
            steps = 2
        step_sleep = duration / steps
        try:
            with self._call_lock:
                self._ipc.down(x1, y1)
                for i in range(1, steps + 1):
                    t = i / steps
                    self._ipc.down(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
                    if step_sleep > 0:
                        time.sleep(step_sleep)
                if hold_at_end > 0:
                    time.sleep(hold_at_end)
                self._ipc.up()
        except self._NemuIpcError as e:
            raise BackendConnectionLost(str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise BackendConnectionLost(
                f"stroke({p1}->{p2}, {duration}s) failed: "
                f"{type(e).__name__}: {e}"
            ) from e
