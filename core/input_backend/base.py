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
from typing import TYPE_CHECKING, Optional, Tuple, Union

import numpy as np

from core import humanize as _humanize
from core.exceptions import MatchTimeout
from core.logging_config import get_logger
from core.vision.button import Button
from core.vision.template_matcher import TemplateMatcher

if TYPE_CHECKING:  # pragma: no cover
    from core.scheduler.throttle import Throttle

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
        *,
        throttle: Optional["Throttle"] = None,
        jitter_radius: Optional[int] = None,
        post_delay_variance: float = 0.0,
        bbox_margin: float = 0.1,
    ) -> None:
        """Store per-account identity. Subclasses must call `super().__init__()`.

        Args:
            account_id: Stable identifier used to namespace logs, caches, and
                runtime state. Required even when only one account exists
                (multi-account readiness, CLAUDE.md S5).
            matcher: Inject a shared `TemplateMatcher`. Defaults to a private
                one. Sharing is fine and saves memory because templates are
                immutable.
            throttle: Optional `Throttle` consulted before every action-emitting
                call (`click`, `swipe`, `drag`, `long_click_xy`). None
                disables rate-limiting (Phase 1-3 behavior; tests pass None
                so they don't pace themselves to death).
            jitter_radius: Behaves as a humanization on/off switch plus
                the disk-jitter radius for raw ``(x, y)`` clicks (where
                no bbox is known). ``None`` or ``0`` disables humanization
                entirely — Button clicks land exactly on match center,
                raw clicks use the 3px legacy ``randint`` fallback. Any
                positive value enables both:
                  * Button click path -> `_jitter_in_button` samples
                    uniformly inside the **full matched bbox** minus
                    ``bbox_margin`` inset (this radius value does NOT
                    cap the bbox spread anymore — was the pre-2026-05
                    behavior; raise ``bbox_margin`` instead if you need
                    tighter clicks on huge buttons).
                  * Raw (x, y) path -> disk-uniform jitter of this radius
                    via `core.humanize.jitter_point`.
            post_delay_variance: Fraction of `Button.post_delay` to fuzz on
                each click. 0 disables fuzzing (Phase 1-3 behavior). 0.3
                yields a uniformly random delay in
                `[post_delay*0.7, post_delay*1.3]`.
            bbox_margin: Fraction of each side to inset when sampling a
                random click inside a Button's matched bbox. ``0.1``
                samples the inner 90% (5% inset per side). ``0`` samples
                anywhere in the bbox. Must be in ``[0, 0.5)``.

        Raises:
            ValueError: `account_id` is empty, `jitter_radius < 0`,
                `post_delay_variance < 0`, or `bbox_margin` not in
                ``[0, 0.5)``.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        if jitter_radius is not None and jitter_radius < 0:
            raise ValueError(f"jitter_radius must be >= 0, got {jitter_radius}")
        if post_delay_variance < 0:
            raise ValueError(
                f"post_delay_variance must be >= 0, got {post_delay_variance}"
            )
        if not 0.0 <= bbox_margin < 0.5:
            raise ValueError(
                f"bbox_margin must be in [0, 0.5), got {bbox_margin}"
            )
        self._account_id = account_id
        self._matcher = matcher or TemplateMatcher()
        self._throttle = throttle
        self._jitter_radius = jitter_radius
        self._post_delay_variance = float(post_delay_variance)
        self._bbox_margin = float(bbox_margin)
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

    @property
    def throttle(self) -> Optional["Throttle"]:
        """Configured `Throttle`, or `None` if rate-limiting is disabled."""
        return self._throttle

    def set_throttle(self, throttle: Optional["Throttle"]) -> None:
        """Replace the throttle after construction (used by main.py wiring)."""
        self._throttle = throttle

    def _acquire_action_slot(self) -> None:
        """Block via throttle (if any) before emitting an input action.

        Called from `click()` and the high-level convenience methods.
        Direct primitives (`click_xy` / `swipe` / `drag` / `long_click_xy`)
        in `NemuIpcBackend` also call this so plugins can't accidentally
        bypass the rate limit by reaching for the low level. `FakeBackend`
        no-ops the primitives so it doesn't need to.
        """
        if self._throttle is not None:
            self._throttle.wait()

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

    def press_back(self) -> None:
        """Press the Android back / system-escape key.

        Default implementation raises `NotImplementedError`. Backends that
        can send system key events (scrcpy, ADB) should override; the nemu
        IPC DLL only handles touch and cannot honor this. Plugin authors
        running on nemu should model "back" as `click_button(BACK_BTN)`
        instead — the `press_back()` action factory will still call this
        method and surface the failure cleanly.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement press_back(). "
            f"Use click_button(BACK_BTN) instead, or switch to a backend "
            f"that supports keyevents."
        )

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

            # Constrain jitter to the matched button's bounding box. The
            # backend's `_jitter` (called inside `click_xy` when
            # randomize=True) is bbox-agnostic disk sampling — a 12px
            # config + a 30x20 button can push the click outside the
            # button's clickable area. We know the template's size here,
            # so sample uniformly inside the bbox (with a small margin)
            # and then tell `click_xy` not to jitter again.
            if randomize and self._jitter_radius is not None and self._jitter_radius > 0:
                try:
                    template = self._matcher.repository.get(target.template)
                    x, y = self._jitter_in_button(
                        x, y, template.shape[:2], target.click_offset
                    )
                    randomize = False
                except Exception:  # noqa: BLE001
                    # Template shape unavailable (test stub, race with
                    # invalidate, ...): fall back to legacy unconstrained
                    # jitter inside click_xy. Better a slightly-off click
                    # than a crash.
                    self._log.debug(
                        "bbox-constrained jitter unavailable for %s; "
                        "falling back to legacy _jitter",
                        target.display_name,
                    )
        else:
            x, y = target
            delay = 0.0 if post_delay is None else post_delay

        # NOTE: throttling lives in the concrete backend's primitives
        # (`click_xy` / `swipe` / `drag` / `long_click_xy`). The screenshot
        # + match step above intentionally does NOT consume rate budget —
        # recognition is read-only and shouldn't count against an "actions
        # per minute" cap.
        self._log.debug("click %s at (%d, %d) delay=%.2f randomize=%s",
                        getattr(target, "display_name", "(xy)"),
                        x, y, delay, randomize)
        self.click_xy(x, y, randomize=randomize)
        if delay > 0:
            # Fuzz the post-delay slightly so back-to-back identical actions
            # don't have suspicious millisecond-accurate cadence. Variance=0
            # falls back to the exact `delay` value.
            _humanize.human_sleep(delay, variance=self._post_delay_variance)
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
    def _jitter(self, x: int, y: int, radius: Optional[int] = None) -> Tuple[int, int]:
        """Return (x, y) shifted by up to ``radius`` pixels.

        Concrete backends call this from `click_xy` / `long_click_xy` when
        `randomize=True`. Kept on the base so every backend humanizes input
        the same way.

        If `radius` is not provided, falls back to the constructor's
        `jitter_radius` (Phase 4 humanize profile); if that is also `None`,
        defaults to the legacy 3px square jitter. When a radius is in
        effect, sampling is disk-uniform via `core.humanize.jitter_point`
        — gentler corners than the legacy `randint` square.

        This bbox-agnostic version is used for raw `(x, y)` clicks where
        no button bounding box is known. Button clicks dispatched via
        `click(Button)` go through `_jitter_in_button` instead, which
        guarantees the click stays inside the captured button frame.
        """
        effective = radius if radius is not None else self._jitter_radius
        if effective is None:
            # Phase 1-3 behavior: square randint jitter at 3px.
            return (
                x + random.randint(-3, 3),
                y + random.randint(-3, 3),
            )
        if effective <= 0:
            return x, y
        return _humanize.jitter_point(x, y, effective)

    def _jitter_in_button(
        self,
        cx: int,
        cy: int,
        template_shape: Tuple[int, int],
        click_offset: Tuple[int, int] = (0, 0),
        *,
        margin: int = 2,
    ) -> Tuple[int, int]:
        """Sample a click point uniformly within the matched button's bbox.

        Why this exists separately from `_jitter`:
            `_jitter` shifts by a configured radius and has no idea how big
            the button it's clicking is. On a 12px disk-jitter profile,
            a 30x20 px button gets clicks landing ±12 in y — outside the
            button — and the game ignores them. This method takes the
            template's actual size and samples inside the **full bbox**
            (minus an inset for safety) so the click is *guaranteed* to
            be on the button as long as the template was captured tight,
            and uses the bbox's natural spread for humanization rather
            than a tiny disk near the center.

        Design (post-2026-05 redesign):
            `self._jitter_radius` is **only an on/off switch + a fallback
            for raw (x, y) clicks**. It is NOT a cap on bbox sampling.
            A 200x200 button with `jitter_radius=12` and `bbox_margin=0.1`
            samples ±80 px in each axis — the full bbox area minus 10%
            per side — not ±12. To get tighter clicks on huge buttons,
            raise ``humanize.bbox_margin`` (e.g. 0.3 = sample inner 40%).

        Inset = max(fractional, pixel-floor):
            * Fractional: ``round(w * self._bbox_margin)`` per side.
            * Pixel floor: ``margin`` (default 2 px) per side — protects
              tiny templates against anti-aliased / sub-pixel edge art
              that the fractional margin rounds to 0.
            * The half-extent on each axis is ``max(0, half_size - inset)``.

        Behavior summary:
            * jitter disabled (`_jitter_radius` None / 0) -> ``(cx, cy)``
            * bbox so small that half-extent is 0 after inset -> ``(cx, cy)``
              (e.g. 4x4 template with default margin: center only — better
              a center-deterministic click than an edge miss)
            * otherwise -> uniformly random in the inset rectangle around
              ``(cx, cy)``. Sampling is rectangular `randint` — natural
              "anywhere on the button" feel.

        Args:
            cx, cy: Click center returned by `TemplateMatcher.find` — this
                already has `click_offset` applied.
            template_shape: ``(height, width)`` from the matched template
                (e.g. ``self._matcher.repository.get(name).shape[:2]``).
            click_offset: `Button.click_offset`. The bbox is centered on
                `(cx - dx, cy - dy)`; sampling happens within that bbox
                and then `click_offset` is re-applied via the same `cx, cy`
                anchor. In practice this means: for a Button with
                `click_offset != (0,0)`, the click stays within an
                identically-sized box shifted by the offset — preserving
                the operator's intent.
            margin: Pixel-floor inset per side (anti-aliased pixels,
                sub-pixel border art, etc.). Default 2. Combined with
                ``self._bbox_margin`` via max() — whichever is larger wins.

        Returns:
            Integer ``(x, y)`` guaranteed to lie within the inset bbox.
        """
        if self._jitter_radius is None or self._jitter_radius <= 0:
            return cx, cy

        h, w = template_shape
        # Effective inset per side: at least `margin` px, scaled up by
        # `bbox_margin` for bigger templates.
        inset_w = max(margin, int(round(w * self._bbox_margin)))
        inset_h = max(margin, int(round(h * self._bbox_margin)))
        half_w = max(0, w // 2 - inset_w)
        half_h = max(0, h // 2 - inset_h)
        if half_w <= 0 and half_h <= 0:
            return cx, cy

        jx = random.randint(-half_w, half_w) if half_w > 0 else 0
        jy = random.randint(-half_h, half_h) if half_h > 0 else 0
        return cx + jx, cy + jy

    # ------------------------------------------------------------------ #
    # Context manager sugar
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "InputBackend":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
