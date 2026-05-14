"""InputBackend abstract layer: high-level dispatch + can't instantiate raw."""

import pytest

from core.exceptions import MatchTimeout
from core.input_backend.base import InputBackend
from core.vision.button import Button


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        InputBackend(account_id="dev")  # type: ignore[abstract]


class _StubBackend(InputBackend):
    """Minimal concrete subclass for exercising base-class methods."""

    def __init__(self, account_id="dev"):
        super().__init__(account_id=account_id)
        self.connected = False
        self.clicks: list[tuple[int, int, bool]] = []
        self.shots = 0
        self._next_screenshot = None
        self._find_returns: list = []

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def screenshot(self):
        import numpy as np
        self.shots += 1
        if self._next_screenshot is not None:
            return self._next_screenshot
        return np.zeros((10, 10, 3), dtype="uint8")

    def click_xy(self, x, y, randomize=True):
        self.clicks.append((x, y, randomize))

    def long_click_xy(self, x, y, duration):
        if duration <= 0:
            raise ValueError("duration must be > 0")
        self.clicks.append((x, y, False))

    def swipe(self, p1, p2, duration):
        if duration <= 0:
            raise ValueError("duration must be > 0")

    def drag(self, p1, p2, duration):
        if duration <= 0:
            raise ValueError("duration must be > 0")


def test_account_id_required():
    with pytest.raises(ValueError):
        _StubBackend(account_id="")


def test_click_with_xy_records_tap():
    b = _StubBackend()
    b.click((100, 200))
    assert b.clicks == [(100, 200, True)]


def test_click_with_button_raises_when_not_visible(monkeypatch):
    b = _StubBackend()
    # Force the matcher to always return None.
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: None)
    with pytest.raises(MatchTimeout):
        b.click(Button.simple("nope/never"))


def test_click_with_button_records_match_point(monkeypatch):
    b = _StubBackend()
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: (321, 654))
    btn = Button.simple("x", post_delay=0)
    point = b.click(btn)
    assert point == (321, 654)
    assert b.clicks[-1][0:2] == (321, 654)


def test_wait_for_returns_immediately_on_hit(monkeypatch):
    b = _StubBackend()
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: (1, 2))
    assert b.wait_for(Button.simple("x"), timeout=1, interval=0.1) == (1, 2)


def test_wait_for_times_out(monkeypatch):
    b = _StubBackend()
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: None)
    with pytest.raises(MatchTimeout):
        b.wait_for(Button.simple("x"), timeout=0.2, interval=0.05)


def test_wait_for_validates_arguments():
    b = _StubBackend()
    with pytest.raises(ValueError):
        b.wait_for(Button.simple("x"), timeout=0)
    with pytest.raises(ValueError):
        b.wait_for(Button.simple("x"), timeout=1, interval=0)


def test_is_visible_proxies_find(monkeypatch):
    b = _StubBackend()
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: None)
    assert b.is_visible(Button.simple("x")) is False
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: (3, 4))
    assert b.is_visible(Button.simple("x")) is True


def test_context_manager_connects_and_disconnects():
    b = _StubBackend()
    with b as opened:
        assert opened.is_connected() is True
    assert b.is_connected() is False
