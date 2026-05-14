"""
`TemplateMatcher` — cv2.matchTemplate wrapped in `Button` semantics.

Keep this module free of Button policy logic (post_delay, retry, etc.) —
those live in the `Button` or in `InputBackend.click`. Matcher only answers
"given this screenshot and this Button, where (if anywhere) is it?".
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np

from core.exceptions import VisionError
from core.logging_config import get_logger
from core.vision.button import Button
from core.vision.template_repository import TemplateRepository

log = get_logger(__name__)


class TemplateMatcher:
    """Match `Button` templates against screenshots."""

    def __init__(self, repository: Optional[TemplateRepository] = None) -> None:
        """Construct a matcher backed by a `TemplateRepository`.

        Args:
            repository: Source of template pixels. If None, a default
                repository rooted at ``<project>/templates`` is created.
        """
        self._repo = repository or TemplateRepository()

    @property
    def repository(self) -> TemplateRepository:
        """The underlying template repository (so callers can invalidate)."""
        return self._repo

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def find(
        self,
        screenshot: np.ndarray,
        button: Button,
    ) -> Optional[Tuple[int, int]]:
        """Locate `button` in `screenshot`.

        Args:
            screenshot: BGR ndarray, shape (H, W, 3), dtype uint8 — exactly
                what `InputBackend.screenshot()` returns. Other formats raise.
            button: Spec to match.

        Returns:
            ``(x, y)`` of the click point in screenshot coords, with
            `button.click_offset` already applied. None if no region above
            `button.threshold` exists.

        Raises:
            VisionError: Screenshot shape/dtype is wrong, or template cannot
                be loaded (re-raised from `TemplateRepository`).
        """
        self._check_screenshot(screenshot)
        template = self._repo.get(button.template)

        crop, offset = self._apply_region(screenshot, button.region)
        match_template, mask = self._prep_template(template)
        if (
            crop.shape[0] < match_template.shape[0]
            or crop.shape[1] < match_template.shape[1]
        ):
            log.debug(
                "search region smaller than template for %s: crop=%s template=%s",
                button.display_name,
                crop.shape,
                match_template.shape,
            )
            return None

        method = cv2.TM_CCOEFF_NORMED
        result = cv2.matchTemplate(crop, match_template, method, mask=mask)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < button.threshold:
            log.debug(
                "no match for %s: best=%.3f threshold=%.3f",
                button.display_name,
                max_val,
                button.threshold,
            )
            return None

        center_x, center_y = self._click_point(max_loc, match_template.shape, offset)
        dx, dy = button.click_offset
        click = (center_x + dx, center_y + dy)
        log.debug(
            "match %s score=%.3f at %s -> click %s",
            button.display_name,
            max_val,
            (center_x, center_y),
            click,
        )
        return click

    def find_all(
        self,
        screenshot: np.ndarray,
        button: Button,
    ) -> List[Tuple[int, int]]:
        """Locate every occurrence of `button` in `screenshot`.

        Args:
            screenshot: Same constraints as `find`.
            button: Spec to match. `click_offset` is applied to every result.

        Returns:
            List of ``(x, y)`` click points in screenshot coords. Empty list
            if nothing scored above `button.threshold`. Results are roughly
            de-duplicated (closer than ~half template size are merged).

        Raises:
            VisionError: Same as `find`.
        """
        self._check_screenshot(screenshot)
        template = self._repo.get(button.template)

        crop, offset = self._apply_region(screenshot, button.region)
        match_template, mask = self._prep_template(template)
        if (
            crop.shape[0] < match_template.shape[0]
            or crop.shape[1] < match_template.shape[1]
        ):
            return []

        result = cv2.matchTemplate(crop, match_template, cv2.TM_CCOEFF_NORMED, mask=mask)
        ys, xs = np.where(result >= button.threshold)

        h, w = match_template.shape[:2]
        merge_radius = max(w, h) // 2
        accepted: List[Tuple[int, int, float]] = []
        for x, y in zip(xs.tolist(), ys.tolist()):
            score = float(result[y, x])
            if any(
                abs(x - ax) <= merge_radius and abs(y - ay) <= merge_radius
                for ax, ay, _ in accepted
            ):
                continue
            accepted.append((x, y, score))

        dx, dy = button.click_offset
        return [
            self._offset_click(self._click_point((x, y), match_template.shape, offset), dx, dy)
            for x, y, _ in accepted
        ]

    def find_by_name(
        self,
        screenshot: np.ndarray,
        template_name: str,
        threshold: float = 0.85,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[int, int]]:
        """Compatibility shim for ad-hoc lookups without a defined Button.

        Equivalent to:
            ``self.find(screenshot, Button(template_name, threshold, region))``

        Prefer the `find(screenshot, Button(...))` form in production code so
        the Button stays a first-class object you can reuse and document.
        """
        return self.find(
            screenshot,
            Button(template=template_name, threshold=threshold, region=region),
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_screenshot(arr: np.ndarray) -> None:
        if not isinstance(arr, np.ndarray):
            raise VisionError(f"screenshot must be ndarray, got {type(arr).__name__}")
        if arr.dtype != np.uint8:
            raise VisionError(f"screenshot dtype must be uint8, got {arr.dtype}")
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise VisionError(
                f"screenshot must be BGR with shape (H, W, 3), got {arr.shape}"
            )

    @staticmethod
    def _apply_region(
        screenshot: np.ndarray,
        region: Optional[Tuple[int, int, int, int]],
    ) -> Tuple[np.ndarray, Tuple[int, int]]:
        """Crop the screenshot to `region`. Returns (crop, (x_offset, y_offset))."""
        if region is None:
            return screenshot, (0, 0)
        x1, y1, x2, y2 = region
        h, w = screenshot.shape[:2]
        x1 = max(0, min(w, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(0, min(h, y2))
        return screenshot[y1:y2, x1:x2], (x1, y1)

    @staticmethod
    def _prep_template(
        template: np.ndarray,
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Normalize template to 3-channel BGR, return (template, mask_or_None)."""
        if template.ndim == 2:
            return cv2.cvtColor(template, cv2.COLOR_GRAY2BGR), None
        if template.shape[2] == 3:
            return template, None
        if template.shape[2] == 4:
            bgr = cv2.cvtColor(template, cv2.COLOR_BGRA2BGR)
            # Alpha as match mask: fully-transparent pixels don't count.
            alpha = template[:, :, 3]
            # cv2 expects a single-channel uint8 mask of the same H,W as template.
            return bgr, alpha
        raise VisionError(
            f"template must be 1/3/4-channel uint8, got shape {template.shape}"
        )

    @staticmethod
    def _click_point(
        top_left: Tuple[int, int],
        template_shape: Tuple[int, ...],
        offset: Tuple[int, int],
    ) -> Tuple[int, int]:
        x, y = top_left
        h, w = template_shape[:2]
        return x + offset[0] + w // 2, y + offset[1] + h // 2

    @staticmethod
    def _offset_click(point: Tuple[int, int], dx: int, dy: int) -> Tuple[int, int]:
        return point[0] + dx, point[1] + dy
