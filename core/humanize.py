"""
`core.humanize` — randomness helpers for making the bot look less robotic.

This module is intentionally side-effect-free (no I/O, no global state).
Every function takes its randomness via an injectable `rng` arg so tests
can be deterministic. Defaults to the module-level `random` so callers
who don't care get sensible behavior.

Three families of helper live here:

* **Coordinate jitter** — `jitter_point(x, y, radius)` returns a uniformly
  random point inside a circle of `radius` pixels around `(x, y)`. The
  base `InputBackend._jitter` uses a square-aligned `randint`-style
  jitter; this one is gentler (round distribution, gaussian-like in the
  middle, harder-edge clipped to the circle) and is what the click/swipe
  default integration calls.

* **Time fuzzing** — `random_delay(base, variance)` returns a perturbed
  duration. `human_sleep(seconds, variance)` sleeps for one. We use uniform
  perturbation in `[1-variance, 1+variance]` because gaussian tails make
  reasoning about worst-case duration harder.

* **Path bias** — `weighted_random_path(paths, cost_fn, ...)` picks one
  of several paths preferring shorter ones (cost^-k weighting). Used by
  `Navigator.goto(humanize=True)` so that "go to settings" doesn't always
  walk the exact same edges in the exact same order.

Why not just use `random.gauss`/`random.uniform` inline at call sites:
  * Centralizing makes the policy auditable (one place to tune jitter
    radius project-wide).
  * Tests can monkeypatch this module to make randomness deterministic
    without touching `random.seed()` globally.
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, List, Optional, Sequence, Tuple, TypeVar

# Module-level defaults — kept in sync with config/config.yaml ranges so
# you can tune the whole project from one knob.
DEFAULT_JITTER_RADIUS = 8
DEFAULT_DELAY_VARIANCE = 0.3
DEFAULT_SLEEP_VARIANCE = 0.2

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Coordinate jitter
# --------------------------------------------------------------------------- #
def random_point_in_rect(
    region: Tuple[int, int, int, int],
    *,
    rng: Optional[random.Random] = None,
) -> Tuple[int, int]:
    """Return a uniformly random ``(x, y)`` inside the inclusive rect.

    Use this for "click hotspot" regions that have no visual feature to
    template — e.g. an invisible expand area in the corner of a screen.
    The whole rect IS the humanization range: the backend's per-call
    ``_jitter`` (±3 px or so) still stacks on top, which is fine — the
    rect picks the macro position, the backend jitter adds micro noise.

    Args:
        region: ``(x1, y1, x2, y2)`` ADB coords. Inclusive on both ends.
            ``x1 == x2`` or ``y1 == y2`` is allowed (collapses to a line
            or a point — caller's responsibility to pass a meaningful
            rect).
        rng: Injection point. Defaults to module `random`.

    Returns:
        Integer ``(x, y)`` with ``x1 <= x <= x2`` and ``y1 <= y <= y2``.

    Raises:
        ValueError: `region` is not a 4-tuple or has ``x1 > x2`` /
            ``y1 > y2`` (caller likely swapped corners).
    """
    if len(region) != 4:
        raise ValueError(f"region must be (x1, y1, x2, y2), got {region!r}")
    x1, y1, x2, y2 = region
    if x1 > x2 or y1 > y2:
        raise ValueError(
            f"region has inverted corners (x1>x2 or y1>y2): {region!r}"
        )
    rng = rng or random
    return rng.randint(x1, x2), rng.randint(y1, y2)


def jitter_point(
    x: int,
    y: int,
    radius: int = DEFAULT_JITTER_RADIUS,
    *,
    rng: Optional[random.Random] = None,
) -> Tuple[int, int]:
    """Return ``(x, y)`` shifted by a uniformly random offset inside a circle.

    Compared to the legacy `InputBackend._jitter` (which uses square
    `randint` shifts), this picks an offset uniformly from a disk of
    `radius` pixels. The result is more "natural-looking" — square-aligned
    jitter has subtly biased corners that some anti-bot heuristics can pick
    up on if they fingerprint touch distributions.

    Args:
        x, y: Original (ADB) coordinates.
        radius: Max pixel displacement. `<= 0` returns the input verbatim.
        rng: Inject a `random.Random` for deterministic tests. Defaults to
            module `random`.

    Returns:
        Integer ``(x', y')`` displaced by up to `radius` pixels.
    """
    if radius <= 0:
        return x, y
    rng = rng or random
    # Uniform-in-disk sampling: angle ~ U[0, 2pi), r ~ sqrt(U[0, 1]) * radius.
    # The sqrt step undoes the area bias that uniform(0, radius) would have.
    angle = rng.uniform(0, 2 * math.pi)
    r = math.sqrt(rng.uniform(0, 1)) * radius
    return int(round(x + r * math.cos(angle))), int(round(y + r * math.sin(angle)))


# --------------------------------------------------------------------------- #
# Time fuzzing
# --------------------------------------------------------------------------- #
def random_delay(
    base: float,
    variance: float = DEFAULT_DELAY_VARIANCE,
    *,
    rng: Optional[random.Random] = None,
) -> float:
    """Return `base * (1 + uniform[-variance, variance])`, clipped to >= 0.

    A `base=1.0, variance=0.3` returns a value in `[0.7, 1.3]`.

    Args:
        base: Center duration in seconds. Must be `>= 0`.
        variance: Fractional spread. `0` => return `base` unchanged. Values
            `> 1` clip the lower bound at 0.
        rng: Inject a `random.Random`. Defaults to module `random`.

    Returns:
        Float in `[max(0, base*(1-variance)), base*(1+variance)]`.

    Raises:
        ValueError: `base < 0` or `variance < 0`.
    """
    if base < 0:
        raise ValueError(f"base must be >= 0, got {base}")
    if variance < 0:
        raise ValueError(f"variance must be >= 0, got {variance}")
    if variance == 0 or base == 0:
        return base
    rng = rng or random
    factor = 1.0 + rng.uniform(-variance, variance)
    return max(0.0, base * factor)


def human_sleep(
    seconds: float,
    variance: float = DEFAULT_SLEEP_VARIANCE,
    *,
    rng: Optional[random.Random] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    """Block for a fuzzed duration around `seconds`.

    NOT stop-aware — use `PluginContext.sleep()` inside plugins if you
    need cooperative cancellation. This helper is for non-plugin code
    (e.g. inside `InputBackend.click` post-delay) where blocking the
    backend's caller is acceptable.

    Args:
        seconds: Center duration.
        variance: Forwarded to `random_delay`.
        rng: Forwarded to `random_delay`.
        sleep: Injection point so tests don't actually block.

    Returns:
        The actual duration slept (so callers can log it).
    """
    actual = random_delay(seconds, variance, rng=rng)
    if actual > 0:
        sleep(actual)
    return actual


# --------------------------------------------------------------------------- #
# Path bias
# --------------------------------------------------------------------------- #
def weighted_random_path(
    paths: Sequence[T],
    cost_fn: Callable[[T], float],
    *,
    bias: float = 1.5,
    rng: Optional[random.Random] = None,
) -> T:
    """Pick one of `paths` with weight ``1 / cost^bias`` per item.

    Shorter paths get higher probability. `bias=0` collapses to uniform
    random; `bias=inf` collapses to "always pick shortest". The default
    `bias=1.5` gives a noticeable but not overwhelming lean toward
    optimal.

    Args:
        paths: Non-empty sequence of candidate paths. Each path's identity
            doesn't matter to this function — only `cost_fn(path)` does.
        cost_fn: Maps a path to its non-negative cost. Zero costs are
            treated as a tiny positive epsilon to avoid divide-by-zero.
        bias: Exponent applied to `1/cost`. Must be `>= 0`.
        rng: Injection point.

    Returns:
        One of the elements of `paths`.

    Raises:
        ValueError: `paths` empty, `bias < 0`, or some cost was negative.
    """
    if not paths:
        raise ValueError("weighted_random_path: paths is empty")
    if bias < 0:
        raise ValueError(f"bias must be >= 0, got {bias}")
    rng = rng or random

    costs: List[float] = []
    for p in paths:
        c = float(cost_fn(p))
        if c < 0:
            raise ValueError(f"cost_fn returned negative cost {c}")
        # Replace 0 with a small epsilon — divide-by-zero would crash
        # weighting; biologically, "zero-cost edge" is also unrealistic.
        costs.append(c if c > 0 else 1e-6)

    if bias == 0:
        weights = [1.0] * len(paths)
    else:
        weights = [1.0 / (c ** bias) for c in costs]

    return rng.choices(list(paths), weights=weights, k=1)[0]


__all__ = [
    "DEFAULT_DELAY_VARIANCE",
    "DEFAULT_JITTER_RADIUS",
    "DEFAULT_SLEEP_VARIANCE",
    "human_sleep",
    "jitter_point",
    "random_delay",
    "random_point_in_rect",
    "weighted_random_path",
]
