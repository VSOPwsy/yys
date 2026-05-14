"""
`Throttle` — rate-limit clicks/swipes to look human and stay safe.

Two policies stack:

* **Min-interval gap** — two consecutive `wait()` calls are separated by
  at least `min_interval` seconds. Defends against "we just submitted 12
  taps in 80ms" patterns.

* **Per-window cap** — at most `max_actions_per_window` calls may complete
  within any sliding `window_seconds` window. Defends against sustained
  high-rate macros (which look like obvious automation).

Both policies are enforced inside `wait()`, which blocks until the next
call is allowed. The throttle holds no thread affinity — multiple worker
threads on the same throttle share its budget. Plugins do NOT instantiate
this themselves; the scheduler builds one per account and injects it
into the `InputBackend` so every input call goes through it.

Time source is `time.monotonic` (immune to clock changes). Tests inject
`clock` and `sleep` to make behavior deterministic.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Optional

from core.exceptions import ThrottleTimeout
from core.logging_config import get_logger

log = get_logger(__name__)


# Reasonable defaults — tuned for "conservative" humanize profile.
DEFAULT_MIN_INTERVAL_S = 0.2  # 200 ms
DEFAULT_MAX_PER_WINDOW = 120
DEFAULT_WINDOW_S = 60.0


class Throttle:
    """Thread-safe min-gap + sliding-window action throttle.

    Construction is cheap; `wait()` is the only method you'll typically
    call. A single `Throttle` instance is shared across all input methods
    on one `InputBackend` so the rate limit reflects the *physical taps*,
    not any one method.
    """

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL_S,
        max_actions_per_window: int = DEFAULT_MAX_PER_WINDOW,
        window_seconds: float = DEFAULT_WINDOW_S,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        name: str = "default",
    ) -> None:
        """Configure the rate limits.

        Args:
            min_interval: Minimum seconds between successive `wait()` returns.
                `0` disables the gap check.
            max_actions_per_window: Cap on completed `wait()` calls within
                any sliding `window_seconds` interval. `0` disables.
            window_seconds: Width of the sliding window in seconds. Must
                be `> 0` if `max_actions_per_window > 0`.
            clock / sleep: Injected for deterministic tests.
            name: Used in log messages. Convention is the account id.

        Raises:
            ValueError: any rate-limit argument is negative, or
                `window_seconds <= 0` with a positive cap.
        """
        if min_interval < 0:
            raise ValueError(f"min_interval must be >= 0, got {min_interval}")
        if max_actions_per_window < 0:
            raise ValueError(
                f"max_actions_per_window must be >= 0, got {max_actions_per_window}"
            )
        if max_actions_per_window > 0 and window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0 when max_actions_per_window > 0, "
                f"got {window_seconds}"
            )

        self._min_interval = float(min_interval)
        self._max_per_window = int(max_actions_per_window)
        self._window = float(window_seconds)
        self._clock = clock
        self._sleep = sleep
        self._name = name

        self._lock = threading.Lock()
        # Timestamps of recent wait() completions. Oldest are popped lazily.
        self._history: Deque[float] = deque()
        self._last_release: float = 0.0
        # Stats (read-only via properties).
        self._calls = 0
        self._total_wait = 0.0

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    @property
    def name(self) -> str:
        return self._name

    @property
    def min_interval(self) -> float:
        return self._min_interval

    @property
    def max_actions_per_window(self) -> int:
        return self._max_per_window

    @property
    def total_calls(self) -> int:
        """Cumulative count of `wait()` returns since construction."""
        with self._lock:
            return self._calls

    @property
    def total_wait_seconds(self) -> float:
        """Cumulative seconds spent blocking in `wait()`."""
        with self._lock:
            return self._total_wait

    def actions_in_window(self) -> int:
        """How many actions have completed within the current window."""
        with self._lock:
            self._prune_window(self._clock())
            return len(self._history)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def wait(self, timeout: Optional[float] = None) -> float:
        """Block until the next action is allowed; record completion.

        Args:
            timeout: Optional upper bound on how long this call may sleep.
                If reached, raises `ThrottleTimeout`. `None` = unbounded.

        Returns:
            Seconds slept (0.0 if the call was allowed immediately).

        Raises:
            ThrottleTimeout: `timeout` expired before allowance opened up.
        """
        start = self._clock()
        slept_total = 0.0
        while True:
            with self._lock:
                now = self._clock()
                self._prune_window(now)
                gap_wait = max(
                    0.0,
                    (self._last_release + self._min_interval) - now,
                )
                window_wait = 0.0
                if self._max_per_window > 0 and len(self._history) >= self._max_per_window:
                    # The oldest action will leave the window at this time.
                    window_wait = max(0.0, self._history[0] + self._window - now)
                needed = max(gap_wait, window_wait)
                if needed <= 0:
                    self._last_release = now
                    self._history.append(now)
                    self._calls += 1
                    self._total_wait += slept_total
                    return slept_total

            if timeout is not None:
                remaining = timeout - (self._clock() - start)
                if remaining <= 0:
                    raise ThrottleTimeout(
                        f"throttle {self._name!r}: did not free up within {timeout:.2f}s "
                        f"(needed {needed:.2f}s more)"
                    )
                needed = min(needed, remaining)

            # Cap each individual sleep to keep us responsive to clock-source
            # injection in tests; this also limits pathological waits.
            self._sleep(min(needed, 1.0))
            slept_total += min(needed, 1.0)

    def reset(self) -> None:
        """Wipe history. Used by tests and on backend reconnect."""
        with self._lock:
            self._history.clear()
            self._last_release = 0.0

    # ------------------------------------------------------------------ #
    # Internals (must be called under the lock)
    # ------------------------------------------------------------------ #
    def _prune_window(self, now: float) -> None:
        cutoff = now - self._window
        while self._history and self._history[0] < cutoff:
            self._history.popleft()

    def __repr__(self) -> str:
        return (
            f"<Throttle name={self._name!r} "
            f"min_interval={self._min_interval}s "
            f"cap={self._max_per_window}/{self._window}s "
            f"calls={self._calls}>"
        )


__all__ = ["Throttle"]
