"""
Recognizers and actions shared between the root demo graph and the `_demo` plugin.

These are *fakes*: instead of matching templates, they read/write a string
attribute (`current_screen`) on a `FakeBackend` provided by `main.py`. That
lets the demo run with zero emulator setup, while still exercising the real
`Navigator` / `PathFinder` / `ScreenRecognizer` code paths.
"""

from __future__ import annotations

from core.navigation.builder import NavigationContext


def demo_recognizer(expected: str):
    """Return a recognizer that fires when the fake backend's screen == `expected`."""

    def _matches(screenshot):
        # screenshot is whatever FakeBackend.screenshot() returned. We tag
        # it as a 1-element ndarray with the screen name embedded in extras
        # via the context, but the recognizer signature only receives the
        # screenshot — so we stash a back-reference on the array itself.
        return getattr(screenshot, "_demo_screen", None) == expected

    _matches.__name__ = f"demo_recognizer({expected})"
    return _matches


def demo_navigate(target: str):
    """Return an action that moves the fake backend to `target`."""

    def _action(ctx: NavigationContext) -> None:
        ctx.backend.current_screen = target

    _action.__name__ = f"demo_navigate({target})"
    return _action
