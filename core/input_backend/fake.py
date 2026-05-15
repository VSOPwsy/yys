"""
`FakeBackend` — in-memory `InputBackend` for demos and tests.

Does NOT talk to any emulator. Holds a single `current_screen` string;
the demo's recognizers (`graphs/_demo_actions.demo_recognizer`) read it
back, and the demo's actions write it. That's enough to exercise the
real `Navigator` / `PathFinder` / `ScreenRecognizer` / scheduler code
paths without spinning up MuMu.

Used by `main.py` for the Phase 3 demo and by `tests/test_scheduler_*`.
Not intended for production gameplay; a real plugin must use a real
backend (e.g. `NemuIpcBackend`).
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from core.input_backend.base import InputBackend
from core.logging_config import get_logger
from core.vision.template_matcher import TemplateMatcher

log = get_logger(__name__)


class _ScreenFrame(np.ndarray):
    """4x4 ndarray that carries a `screen_id` tag for demo recognizers.

    Real backends return plain BGR ndarrays. Demo recognizers read the
    extra `_demo_screen` attribute to decide if the current vertex is
    "us". Real `Button`-based recognizers don't care about the tag and
    will simply fail to match (which is fine, the demo doesn't use them).
    """

    def __new__(cls, screen_id: str):
        obj = np.zeros((4, 4, 3), dtype=np.uint8).view(cls)
        obj._demo_screen = screen_id
        return obj


class FakeBackend(InputBackend):
    """Minimal `InputBackend` whose entire state is one screen-id string.

    Use as a context manager:

        with FakeBackend("main_menu", account_id="alice") as backend:
            ...

    Or call `connect()` manually. Either way, `current_screen` is the
    "game state" — actions mutate it, recognizers read it.
    """

    def __init__(
        self,
        initial_screen: str = "main_menu",
        *,
        account_id: str = "fake",
        matcher: TemplateMatcher | None = None,
        throttle=None,  # Optional[core.scheduler.throttle.Throttle]
        jitter_radius: int | None = None,
        post_delay_variance: float = 0.0,
        bbox_margin: float = 0.1,
    ) -> None:
        super().__init__(
            account_id=account_id,
            matcher=matcher,
            throttle=throttle,
            jitter_radius=jitter_radius,
            post_delay_variance=post_delay_variance,
            bbox_margin=bbox_margin,
        )
        self.current_screen = initial_screen
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def screenshot(self) -> np.ndarray:
        return _ScreenFrame(self.current_screen)

    def click_xy(self, x: int, y: int, randomize: bool = True) -> None:
        log.debug("FakeBackend.click_xy(%d, %d) — no-op", x, y)

    def long_click_xy(self, x: int, y: int, duration: float) -> None:
        if duration <= 0:
            raise ValueError("duration must be > 0")
        log.debug("FakeBackend.long_click_xy(%d, %d, %.3f) — no-op", x, y, duration)

    def swipe(self, p1: Tuple[int, int], p2: Tuple[int, int], duration: float) -> None:
        if duration <= 0:
            raise ValueError("duration must be > 0")
        log.debug("FakeBackend.swipe(%s -> %s, %.3f) — no-op", p1, p2, duration)

    def drag(self, p1: Tuple[int, int], p2: Tuple[int, int], duration: float) -> None:
        if duration <= 0:
            raise ValueError("duration must be > 0")
        log.debug("FakeBackend.drag(%s -> %s, %.3f) — no-op", p1, p2, duration)
