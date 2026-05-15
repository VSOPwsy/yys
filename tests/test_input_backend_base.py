"""InputBackend abstract layer: high-level dispatch + can't instantiate raw."""

import random

import pytest

from core.exceptions import MatchTimeout
from core.input_backend.base import InputBackend
from core.vision.button import Button


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        InputBackend(account_id="dev")  # type: ignore[abstract]


class _StubBackend(InputBackend):
    """Minimal concrete subclass for exercising base-class methods."""

    def __init__(self, account_id="dev", **kwargs):
        # Forward base kwargs (jitter_radius, post_delay_variance, throttle,
        # matcher) so individual tests can opt into Phase 4 behaviors.
        super().__init__(account_id=account_id, **kwargs)
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


# --------------------------------------------------------------------------- #
# _jitter_in_button — full-bbox sampling for Button clicks (2026-05 redesign)
# --------------------------------------------------------------------------- #
# Earlier design (Phase 4 first cut) capped sampling by `jitter_radius`,
# which left only ~25% of a 60x40 button's area reachable on the default
# 12px profile — clicks looked machine-precise. Current design: sample the
# full bbox minus a fractional `bbox_margin` inset (with a 2px pixel
# floor). `jitter_radius` is now ONLY an on/off switch + the raw-click
# disk radius — it does NOT cap bbox sampling.
#
# The method must:
#   (1) be a no-op when jitter is disabled,
#   (2) sample (with safety margin) the FULL bbox when enabled,
#   (3) honor bbox_margin to tighten sampling on big buttons,
#   (4) collapse to (cx, cy) when the bbox is too small to inset,
#   (5) never produce a click outside the resulting (cx ± half_x, cy ± half_y)
#       box, across many samples.

def test_jitter_in_button_disabled_when_radius_none():
    b = _StubBackend()  # jitter_radius defaults to None
    assert b._jitter_in_button(100, 200, (50, 50)) == (100, 200)


def test_jitter_in_button_disabled_when_radius_zero():
    b = _StubBackend(jitter_radius=0)
    assert b._jitter_in_button(100, 200, (50, 50)) == (100, 200)


def test_jitter_in_button_small_button_uses_full_bbox():
    # Button is 30x20, jitter_radius=12 (just an enable), bbox_margin=0.1.
    # Expected per-axis half-extents (no radius cap anymore):
    #   inset_w = max(2, round(30 * 0.1)) = max(2, 3) = 3
    #   inset_h = max(2, round(20 * 0.1)) = max(2, 2) = 2
    #   half_w = 30//2 - 3 = 12
    #   half_h = 20//2 - 2 = 8
    b = _StubBackend(jitter_radius=12)  # bbox_margin defaults to 0.1
    rng_min_x, rng_max_x = 100 - 12, 100 + 12
    rng_min_y, rng_max_y = 200 - 8, 200 + 8
    saw_min_y, saw_max_y = 1_000, -1_000
    for _ in range(400):
        x, y = b._jitter_in_button(100, 200, (20, 30))
        assert rng_min_x <= x <= rng_max_x, f"x={x} outside bbox-w"
        assert rng_min_y <= y <= rng_max_y, f"y={y} outside bbox-h"
        saw_min_y = min(saw_min_y, y)
        saw_max_y = max(saw_max_y, y)
    # Confirm bbox-h is *actually engaged* — random sampling should hit
    # the extreme y values across 400 trials, not just stick to ±0.
    assert saw_min_y <= rng_min_y + 2
    assert saw_max_y >= rng_max_y - 2


def test_jitter_in_button_big_button_samples_full_bbox_not_radius_capped():
    # 2026-05 redesign assertion: a 200x200 button with a SMALL radius=4
    # still samples the WHOLE bbox (minus bbox_margin inset) — radius
    # does NOT cap bbox sampling anymore. Pre-redesign this test asserted
    # ±4; that behavior is intentionally gone.
    #   inset = max(2, round(200 * 0.1)) = max(2, 20) = 20
    #   half = 200//2 - 20 = 80
    b = _StubBackend(jitter_radius=4)  # tiny radius — but doesn't cap bbox
    saw_min_x, saw_max_x = 1_000, -1_000
    for _ in range(400):
        x, y = b._jitter_in_button(500, 500, (200, 200))
        assert 420 <= x <= 580, f"x={x} outside expected ±80 spread"
        assert 420 <= y <= 580, f"y={y} outside expected ±80 spread"
        saw_min_x = min(saw_min_x, x)
        saw_max_x = max(saw_max_x, x)
    # Must actually use the wide range, not stick near center.
    assert saw_min_x <= 440, f"saw_min_x={saw_min_x} suspiciously close to center"
    assert saw_max_x >= 560, f"saw_max_x={saw_max_x} suspiciously close to center"


def test_jitter_in_button_bbox_margin_tightens_sampling_on_big_buttons():
    # bbox_margin=0.4 on a 200x200 button: inset_w = max(2, 80) = 80,
    # half_w = 100 - 80 = 20. Clicks should stay within ±20 even though
    # the bbox is much bigger.
    b = _StubBackend(jitter_radius=12, bbox_margin=0.4)
    for _ in range(200):
        x, y = b._jitter_in_button(500, 500, (200, 200))
        assert 480 <= x <= 520, f"x={x} outside ±20 (bbox_margin=0.4)"
        assert 480 <= y <= 520, f"y={y} outside ±20 (bbox_margin=0.4)"


def test_jitter_in_button_tiny_button_returns_center():
    # 4x4 button: fractional margin rounds to 0, so the 2px floor wins.
    # half_w = max(0, 2 - 2) = 0, half_h = max(0, 2 - 2) = 0. Both axes
    # collapse → return center. Better a center-deterministic click than
    # a randomized edge miss.
    b = _StubBackend(jitter_radius=12)
    assert b._jitter_in_button(50, 60, (4, 4)) == (50, 60)


def test_jitter_in_button_uses_module_random_so_seeded_runs_reproduce():
    # Sanity check that the implementation uses `random.randint` (not a
    # private RNG), so a seeded random.seed() makes the behavior
    # deterministic in test runs.
    b = _StubBackend(jitter_radius=12)
    random.seed(42)
    first = [b._jitter_in_button(100, 200, (50, 50)) for _ in range(10)]
    random.seed(42)
    second = [b._jitter_in_button(100, 200, (50, 50)) for _ in range(10)]
    assert first == second


def test_click_button_constrains_to_bbox_via_jitter_in_button(monkeypatch):
    # End-to-end: click(Button) with jitter_radius configured should pass
    # click_xy a point INSIDE the bbox AND with randomize=False (so the
    # backend's own _jitter does not double up and push outside again).
    b = _StubBackend(jitter_radius=12)
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: (100, 200))
    # Inject a stub template via the repository so .shape[:2] works.
    import numpy as np
    fake_tmpl = np.zeros((20, 30, 3), dtype="uint8")  # h=20, w=30
    monkeypatch.setattr(b.matcher.repository, "get", lambda name: fake_tmpl)

    btn = Button.simple("x", post_delay=0)
    for _ in range(50):
        x, y = b.click(btn)
        # Post-redesign expectations, bbox_margin=0.1 default:
        #   inset_w = max(2, round(30*0.1)) = max(2, 3) = 3 -> half_w = 12
        #   inset_h = max(2, round(20*0.1)) = max(2, 2) = 2 -> half_h = 8
        assert 88 <= x <= 112, f"x={x} outside bbox-w"
        assert 192 <= y <= 208, f"y={y} outside bbox-h"
        # And the click_xy call MUST have randomize=False so the backend
        # doesn't re-jitter past the bbox.
        assert b.clicks[-1][2] is False, "click_xy got randomize=True; double jitter"


def test_click_button_falls_back_to_legacy_jitter_when_template_unavailable(monkeypatch):
    # If the template can't be loaded (no PNG, race with invalidate), click()
    # must still work — falling back to legacy _jitter inside click_xy with
    # randomize=True (which the stub records but doesn't actually apply).
    b = _StubBackend(jitter_radius=12)
    monkeypatch.setattr(b.matcher, "find", lambda *a, **k: (321, 654))

    def boom(name):
        raise RuntimeError("template gone")
    monkeypatch.setattr(b.matcher.repository, "get", boom)

    btn = Button.simple("x", post_delay=0)
    x, y = b.click(btn)
    assert (x, y) == (321, 654)
    # Fell back to legacy jitter path → click_xy received randomize=True.
    assert b.clicks[-1] == (321, 654, True)
