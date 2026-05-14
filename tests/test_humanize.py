"""Unit tests for `core.humanize`: jitter, delays, path weighting."""

from __future__ import annotations

import math
import random

import pytest

from core.humanize import (
    human_sleep,
    jitter_point,
    random_delay,
    weighted_random_path,
)


# --------------------------------------------------------------------------- #
# jitter_point
# --------------------------------------------------------------------------- #
def test_jitter_point_zero_radius_is_identity():
    assert jitter_point(100, 200, radius=0) == (100, 200)
    assert jitter_point(100, 200, radius=-5) == (100, 200)


def test_jitter_point_stays_inside_disk():
    rng = random.Random(42)
    cx, cy = 500, 300
    radius = 10
    for _ in range(500):
        x, y = jitter_point(cx, cy, radius=radius, rng=rng)
        # +1 tolerance for int rounding.
        assert math.hypot(x - cx, y - cy) <= radius + 1


def test_jitter_point_uses_injected_rng_for_determinism():
    rng1 = random.Random(7)
    rng2 = random.Random(7)
    a = [jitter_point(0, 0, radius=20, rng=rng1) for _ in range(5)]
    b = [jitter_point(0, 0, radius=20, rng=rng2) for _ in range(5)]
    assert a == b


# --------------------------------------------------------------------------- #
# random_delay
# --------------------------------------------------------------------------- #
def test_random_delay_zero_variance_returns_base():
    assert random_delay(1.0, variance=0.0) == 1.0


def test_random_delay_zero_base_returns_zero():
    assert random_delay(0.0, variance=0.5) == 0.0


def test_random_delay_bounded_by_variance():
    rng = random.Random(123)
    base = 2.0
    variance = 0.3
    for _ in range(200):
        d = random_delay(base, variance=variance, rng=rng)
        assert base * (1 - variance) - 1e-9 <= d <= base * (1 + variance) + 1e-9


def test_random_delay_validates_args():
    with pytest.raises(ValueError):
        random_delay(-1.0, variance=0.3)
    with pytest.raises(ValueError):
        random_delay(1.0, variance=-0.1)


def test_random_delay_variance_gt_one_clips_to_zero():
    rng = random.Random(0)
    # With variance=1.2 the lower bound is `base * -0.2 = -0.4`; we clip to 0.
    for _ in range(50):
        d = random_delay(1.0, variance=1.2, rng=rng)
        assert d >= 0


# --------------------------------------------------------------------------- #
# human_sleep
# --------------------------------------------------------------------------- #
def test_human_sleep_invokes_sleep_with_fuzzed_duration():
    calls = []
    rng = random.Random(1)
    actual = human_sleep(0.5, variance=0.2, rng=rng, sleep=calls.append)
    assert len(calls) == 1
    assert math.isclose(calls[0], actual)
    assert 0.4 - 1e-9 <= actual <= 0.6 + 1e-9


def test_human_sleep_skips_zero():
    calls = []
    actual = human_sleep(0, variance=0.5, sleep=calls.append)
    assert actual == 0
    assert calls == []


# --------------------------------------------------------------------------- #
# weighted_random_path
# --------------------------------------------------------------------------- #
def test_weighted_random_path_picks_only_path():
    assert weighted_random_path(["only"], lambda _: 1.0) == "only"


def test_weighted_random_path_zero_bias_is_uniform():
    rng = random.Random(0)
    counts = {"short": 0, "long": 0}
    paths = ["short", "long"]
    for _ in range(2000):
        pick = weighted_random_path(
            paths, lambda p: 1.0 if p == "short" else 100.0,
            bias=0.0, rng=rng,
        )
        counts[pick] += 1
    # 95% confidence: |counts - 1000| <= 100 for uniform-ish.
    assert 800 < counts["short"] < 1200
    assert 800 < counts["long"] < 1200


def test_weighted_random_path_biases_short():
    rng = random.Random(0)
    counts = {"short": 0, "long": 0}
    paths = ["short", "long"]
    for _ in range(2000):
        pick = weighted_random_path(
            paths, lambda p: 1.0 if p == "short" else 5.0,
            bias=2.0, rng=rng,
        )
        counts[pick] += 1
    # With cost ratio 5x and bias=2 -> 25x more likely to pick "short".
    assert counts["short"] > counts["long"] * 5


def test_weighted_random_path_validates_args():
    with pytest.raises(ValueError):
        weighted_random_path([], lambda _: 1.0)
    with pytest.raises(ValueError):
        weighted_random_path(["a"], lambda _: 1.0, bias=-0.1)
    with pytest.raises(ValueError):
        weighted_random_path(["a"], lambda _: -1.0)


def test_weighted_random_path_handles_zero_cost():
    """Zero-cost paths get an epsilon weight (not infinite)."""
    rng = random.Random(0)
    # Should not raise.
    pick = weighted_random_path(
        ["a", "b"], lambda p: 0.0 if p == "a" else 1.0, bias=2.0, rng=rng,
    )
    assert pick in ("a", "b")
