"""
`InputBackend` — abstract Strategy interface for sending input + reading frames.

Why a base class:
  * lets us swap nemu IPC for scrcpy / MAA / real ADB without touching plugins,
  * locks down the high-level helpers (`click(Button)`, `wait_for`, `find`,
    `is_visible`) at one well-tested level so concrete backends only worry
    about the low-level primitives,
  * forces every backend to accept `account_id` at construction so we cannot
    accidentally grow a singleton.

Concrete backends:
  * Implement the abstract primitives (`connect`/`disconnect`/...).
  * Translate native exceptions into subclasses of `InputBackendError` from
    `core.exceptions`. Letting `NemuIpcError` leak past this layer would
    couple every plugin to vendor/alas.
"""

from __future__ import annotations

import abc
import random
import time
from typing import Optional, Tuple, Union

import numpy as np

from core.exceptions import MatchTimeout
from core.logging_config import get_logger
from core.vision.button import Button
from core.vision.template_matcher import TemplateMatcher

ClickTarget = Union[Button, Tuple[int, int]]


class InputBackend(abc.ABC):
    """Abstract base for everything that talks to an emulator/device.

    Construction is per-account. Concrete subclasses must accept
    `account_id` as the first positional or keyword argument.
    """

    def __init__(
        self,
        account_id: str,
        matcher: Optional[TemplateMatcher] = None,
    ) -> None:
        """Store per-account identity. Subclasses must call `super().__init__()`.

        Args:
            account_id: Stable identifier used to namespace logs, caches, and
                runtime state. Required even when only one account exists
                (multi-account readiness, CLAUDE.md S5).
            matcher: Inject a shared `TemplateMatcher`. Defaults to a private
                one. Sharing is fine and saves memory because templates are
                immutable.

        Raises:
            ValueError: `account_id` is empty.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        self._account_id = account_id
        self._matcher = matcher or TemplateMatcher()
        self._log = get_logger(f"input.{account_id}")

    # ------------------------------------------------------------------ #
    # Identity / lifecycle / introspection
    # ------------------------------------------------------------------ #
    @property
    def account_id(self) -> str:
        """Account this backend is bound to. Set at construction, never mutated."""
        return self._account_id

    @property
    def matcher(self) -> TemplateMatcher:
        """Shared template matcher (lets callers reach the template cache)."""
        return self._matcher

    @abc.abstractmethod
    def connect(self) -> None:
        """Open the underlying transport. Must be idempotent.

        Raises:
            BackendNotAvailable: Backend cannot run here (missing DLL, bad path).
            BackendConnectionLost: Initial handshake with the device failed.
        """

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the underlying transport. Must be idempotent."""

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """True iff the backend currently holds a working transport."""

    # ------------------------------------------------------------------ #
    # Low-level primitives — concrete backends implement these
    # ------------------------------------------------------------------ #
    @abc.abstractmethod
    def screenshot(self) -> np.ndarray:
        """Grab one frame.

        Returns:
            BGR ndarray, shape (H, W, 3), dtype uint8. **Not** BGRA, **not**
            vertically flipped — concrete backends must normalize before
            returning. Plugin code should never need to know about BGRA.

        Raises:
            BackendNotAvailable / BackendConnectionLost.
        """

    @abc.abstractmethod
    def click_xy(self, x: int, y: int, randomize: bool = True) -> None:
        """Tap at ADB-coordinates (x, y).

        Args:
            x, y: ADB-screen pixel coordinates (no rotation). Origin top-left.
            randomize: If True, the backend should jitter the actual touch
                point by a few pixels to look less robotic. Default True;
                set False when you absolutely need a specific pixel.

        Raises:
            BackendNotAvailable / BackendConnectionLost.
        """

    @abc.abstractmethod
    def long_click_xy(self, x: int, y: int, duration: float) -> None:
        """Press and hold at (x, y) for `duration` seconds, then release.

        Raises:
            BackendNotAvailable / BackendConnectionLost.
            ValueError: `duration <= 0`.
        """

    @abc.abstractmethod
    def swipe(
        self,
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        duration: float,
    ) -> None:
        """Fast directional swipe from p1 to p2 over `duration` seconds.

        Semantically a flick: the finger leaves the screen at the endpoint
        with momentum. Use `drag` if you need a slow controlled motion
        without inertial scroll behavior.

        Raises:
            BackendNotAvailable / BackendConnectionLost.
            ValueError: `duration <= 0`.
        """

    @abc.abstractmethod
    def drag(
        self,
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        duration: float,
    ) -> None:
        """Slow controlled drag from p1 to p2 over `duration` seconds.

        Semantically a "hold + move + release": no inertial scroll. Used for
        dragging items in inventories, slider controls, etc.

        Raises:
            BackendNotAvailable / BackendConnectionLost.
            ValueError: `duration <= 0`.
        """

    # ------------------------------------------------------------------ #
    # High-level helpers — implemented once on the base. Don't override.
    # ------------------------------------------------------------------ #
    def click(
        self,
        target: ClickTarget,
        *,
        post_delay: Optional[float] = None,
        randomize: bool = True,
    ) -> Tuple[int, int]:
        """Dispatch click on a Button or a raw (x, y).

        Behavior:
            * `(x, y)` -> immediate tap at that coord.
            * `Button` -> screenshot, match, tap at the match center (with
              `click_offset`). Honors `Button.post_delay` if `post_delay`
              kwarg is not given.

        Args:
            target: Where to click.
            post_delay: Seconds to sleep after the click. Defaults to the
                Button's `post_delay`, or 0 for raw coords.
            randomize: Jitter the touch point a few pixels. See `click_xy`.

        Returns:
            The actual ``(x, y)`` that was tapped (post-randomization is
            performed inside `click_xy` and not reflected here; callers who
            need the exact tapped pixel should subclass).

        Raises:
            TemplateNotFound: Button's template file is missing.
            MatchTimeout: Button-target not visible (single-shot, no retry).
            BackendNotAvailable / BackendConnectionLost.
        """
        if isinstance(target, Button):
            shot = self.screenshot()
            point = self._matcher.find(shot, target)
            if point is None:
                raise MatchTimeout(
                    f"Button {target.display_name!r} not found on current screen"
                )
            x, y = point
            delay = target.post_delay if post_delay is None else post_delay
        else:
            x, y = target
            delay = 0.0 if post_delay is None else post_delay

        self._log.debug("click %s at (%d, %d) delay=%.2f",
                        getattr(target, "display_name", "(xy)"), x, y, delay)
        self.click_xy(x, y, randomize=randomize)
        if delay > 0:
            time.sleep(delay)
        return x, y

    def find(self, button: Button) -> Optional[Tuple[int, int]]:
        """One-shot screenshot + match for `button`.

        Returns:
            ``(x, y)`` click point or None if not visible right now.

        Raises:
            TemplateNotFound: Button's template file is missing.
            BackendNotAvailable / BackendConnectionLost.
        """
        shot = self.screenshot()
        return self._matcher.find(shot, button)

    def is_visible(self, button: Button) -> bool:
        """True iff `button` is currently visible. Sugar over `find`."""
        return self.find(button) is not None

    def wait_for(
        self,
        button: Button,
        timeout: float = 10.0,
        interval: float = 0.5,
    ) -> Tuple[int, int]:
        """Block until `button` is visible or `timeout` elapses.

        Args:
            button: What to wait for.
            timeout: Seconds. Measured against `time.monotonic` so suspension
                of the system clock doesn't skew it.
            interval: Sleep between polls. Smaller = faster reaction +
                higher screenshot cost.

        Returns:
            ``(x, y)`` click point at the moment it became visible.

        Raises:
            MatchTimeout: Button never showed up before `timeout`.
            TemplateNotFound: Button's template file is missing.
            BackendNotAvailable / BackendConnectionLost.
            ValueError: `timeout <= 0` or `interval <= 0`.
        """
        if timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {timeout}")
        if interval <= 0:
            raise ValueError(f"interval must be > 0, got {interval}")

        deadline = time.monotonic() + timeout
        attempts = 0
        while True:
            point = self.find(button)
            if point is not None:
                self._log.debug(
                    "wait_for %s appeared after %d attempts", button.display_name, attempts
                )
                return point
            attempts += 1
            if time.monotonic() >= deadline:
                raise MatchTimeout(
                    f"Button {button.display_name!r} did not appear within "
                    f"{timeout:.1f}s ({attempts} attempts)"
                )
            time.sleep(interval)

    # ------------------------------------------------------------------ #
    # Helpers shared by concrete backends
    # ------------------------------------------------------------------ #
    @staticmethod
    def _jitter(x: int, y: int, radius: int = 3) -> Tuple[int, int]:
        """Return (x, y) shifted by up to ``radius`` pixels in each axis.

        Concrete backends call this from `click_xy` / `long_click_xy` when
        `randomize=True`. Kept on the base so every backend humanizes input
        the same way.
        """
        if radius <= 0:
            return x, y
        return (
            x + random.randint(-radius, radius),
            y + random.randint(-radius, radius),
        )

    # ------------------------------------------------------------------ #
    # Context manager sugar
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "InputBackend":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
