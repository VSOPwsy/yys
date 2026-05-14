"""
`Button` — the only sanctioned way to describe a clickable UI element.

Hard rule from CLAUDE.md S5: no scattered (x,y) literals, no one-shot
`click_template(path)`. Every clickable thing in the codebase must be a
`Button` instance defined somewhere stable (typically alongside the plugin
that owns the screen it appears on).

`Button` is intentionally lightweight: just metadata. Pixel data lives in
`TemplateRepository`; matching lives in `TemplateMatcher`. That separation
lets us pass `Button` objects across thread boundaries and share them
between accounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional, Tuple


@dataclass(frozen=True)
class Button:
    """Immutable spec for a clickable UI element.

    Attributes:
        template: Template path relative to ``templates/``, without the
            ``.png`` suffix. Example: ``"main_menu/profile_btn"`` resolves to
            ``templates/main_menu/profile_btn.png``. Use forward slashes;
            `TemplateRepository` normalizes them per platform.
        threshold: cv2.matchTemplate score above which a region counts as a
            match. 0.85 is a sane default for clean game UIs; lower it for
            anti-aliased text, raise it for visually noisy areas.
        region: Optional search rectangle ``(x1, y1, x2, y2)`` in ADB-screen
            coordinates (so a 1920x1080 game uses 0..1920 for x). ``None``
            searches the whole screenshot. Restricting the region is the
            cheapest perf win and the cheapest false-positive guard.
        click_offset: ``(dx, dy)`` applied to the matched region's center
            when clicking. Useful when the click target is visually distinct
            from the template (e.g. template is an icon, click target is a
            label to its right).
        post_delay: Seconds to ``time.sleep`` after the click. Models the
            UI's animation cost; lets the next screenshot see the updated
            state. Override at click time via `click(button, post_delay=...)`.
        retry: Times `wait_for` rechecks before giving up. Mostly informational
            for tuning; `wait_for` actually uses `timeout` + `interval`.
        name: Human-readable label. Defaults to `template`. Shown in logs
            and errors, never used for matching.
    """

    template: str
    threshold: float = 0.85
    region: Optional[Tuple[int, int, int, int]] = None
    click_offset: Tuple[int, int] = (0, 0)
    post_delay: float = 0.5
    retry: int = 3
    name: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        if not self.template:
            raise ValueError("Button.template must be a non-empty string")
        if not (0.0 < self.threshold <= 1.0):
            raise ValueError(
                f"Button.threshold must be in (0, 1], got {self.threshold}"
            )
        if self.region is not None:
            x1, y1, x2, y2 = self.region
            if x1 >= x2 or y1 >= y2:
                raise ValueError(
                    f"Button.region must be (x1,y1,x2,y2) with x1<x2 and y1<y2, "
                    f"got {self.region}"
                )
        if self.post_delay < 0:
            raise ValueError(f"Button.post_delay must be >= 0, got {self.post_delay}")
        if self.retry < 0:
            raise ValueError(f"Button.retry must be >= 0, got {self.retry}")

    @property
    def display_name(self) -> str:
        """Resolved label for logs: explicit `name` if set, else `template`."""
        return self.name or self.template

    # ------------------------------------------------------------------ #
    # Convenience constructors. Keep these factory-style so the dataclass
    # itself stays a plain immutable record.
    # ------------------------------------------------------------------ #
    @classmethod
    def simple(cls, template: str, **overrides: object) -> "Button":
        """Build a Button with only a template path and optional overrides.

        Args:
            template: Same semantics as the dataclass attribute.
            **overrides: Forwarded to the dataclass constructor.

        Returns:
            A new `Button` instance.
        """
        return cls(template=template, **overrides)  # type: ignore[arg-type]

    @classmethod
    def in_region(
        cls,
        template: str,
        region: Tuple[int, int, int, int],
        **overrides: object,
    ) -> "Button":
        """Build a Button restricted to a search region.

        Args:
            template: Same semantics as the dataclass attribute.
            region: ``(x1, y1, x2, y2)`` search box in ADB coordinates.
            **overrides: Forwarded to the dataclass constructor.

        Returns:
            A new `Button` instance with `region` set.
        """
        return cls(template=template, region=region, **overrides)  # type: ignore[arg-type]

    def with_(self, **overrides: object) -> "Button":
        """Return a copy of this Button with selected fields replaced.

        Useful for per-call overrides without mutating the original:
            ``profile_btn.with_(post_delay=2.0)``.
        """
        return replace(self, **overrides)  # type: ignore[arg-type]
