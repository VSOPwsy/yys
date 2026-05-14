"""
`LongRunPolicy` — background watchdog that enforces rest cycles + daily cap.

Phase 4 anti-detection layer. Two policies:

* **Rest cycle**: after `rest_every` seconds of cumulative *running* time
  the watchdog pauses every worker for `rest_duration` seconds, then
  resumes. The plugin's `should_pause()` notices and idles via
  `wait_until_resumed()`; nothing in the plugin code changes.

* **Daily runtime cap**: when cumulative running time hits
  `daily_max_runtime`, the watchdog stops every worker and signals the
  main thread (via the `on_daily_cap_reached` callback) to exit.

Pause / resume / stop calls are all routed through `scheduler.submit()`
so they execute on the dispatcher thread alongside hotkey commands —
no double-locking, no priority inversions.

The watchdog itself runs on a single daemon thread that polls at
`tick_interval` seconds (default 5s). That's plenty granular: rest
cycles are measured in minutes.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from core.logging_config import get_logger

log = get_logger(__name__)


# Default poll cadence. Small enough to be responsive, large enough to
# barely show up in CPU traces.
_TICK_INTERVAL_S = 5.0


class LongRunPolicy:
    """Watchdog enforcing rest cycles + daily cap on a `Scheduler`."""

    def __init__(
        self,
        scheduler,  # core.scheduler.scheduler.Scheduler — Any to dodge import cycle
        *,
        daily_max_runtime: float,
        rest_every: float,
        rest_duration: float,
        on_daily_cap_reached: Optional[Callable[[], None]] = None,
        tick_interval: float = _TICK_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Configure but do not yet start the watchdog.

        Args:
            scheduler: The `Scheduler` instance to drive. Watchdog calls
                `pause_all` / `resume_all` / `stop_all` via `submit`.
            daily_max_runtime: Seconds of total runtime before the daily
                cap fires. Must be `> 0`.
            rest_every: Seconds of *running* (not paused, not stopped)
                time between rest cycles. `0` disables rest cycles.
            rest_duration: Seconds to stay paused once a rest fires.
                Ignored when `rest_every == 0`.
            on_daily_cap_reached: Optional callback invoked from the
                watchdog thread when the daily cap is reached. The
                scheduler shutdown is invoked first; the callback is for
                main.py to break out of its wait loop.
            tick_interval: Polling cadence (seconds).
            clock / sleep: Test-injection points.

        Raises:
            ValueError: invalid durations.
        """
        if daily_max_runtime <= 0:
            raise ValueError(
                f"daily_max_runtime must be > 0, got {daily_max_runtime}"
            )
        if rest_every < 0:
            raise ValueError(f"rest_every must be >= 0, got {rest_every}")
        if rest_every > 0 and rest_duration <= 0:
            raise ValueError(
                "rest_duration must be > 0 when rest_every is set, "
                f"got rest_duration={rest_duration}"
            )
        if tick_interval <= 0:
            raise ValueError(f"tick_interval must be > 0, got {tick_interval}")

        self._scheduler = scheduler
        self._daily_max = float(daily_max_runtime)
        self._rest_every = float(rest_every)
        self._rest_duration = float(rest_duration)
        self._on_daily_cap = on_daily_cap_reached
        self._tick_interval = float(tick_interval)
        self._clock = clock
        self._sleep = sleep

        # Internal state — all read/written only by the watchdog thread,
        # except `_stop` and `_thread` (touched by start / stop).
        self._started_at: Optional[float] = None
        self._last_rest_at: Optional[float] = None
        self._daily_cap_triggered = False

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Spin up the watchdog thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._started_at = self._clock()
        self._last_rest_at = self._started_at
        self._daily_cap_triggered = False
        self._thread = threading.Thread(
            target=self._run,
            name="LongRunPolicy",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "LongRunPolicy started: daily_max=%.1fmin rest_every=%.1fmin "
            "rest_duration=%.1fmin",
            self._daily_max / 60.0, self._rest_every / 60.0,
            self._rest_duration / 60.0,
        )

    def stop(self) -> None:
        """Signal the watchdog to exit and join it. Idempotent."""
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=self._tick_interval * 2)
        self._thread = None

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    @property
    def daily_cap_triggered(self) -> bool:
        """True once the daily-cap branch has fired (test hook)."""
        return self._daily_cap_triggered

    @property
    def elapsed(self) -> float:
        """Seconds since `start()`. 0 if not started."""
        if self._started_at is None:
            return 0.0
        return max(0.0, self._clock() - self._started_at)

    # ------------------------------------------------------------------ #
    # The watchdog loop
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        log.info("LongRunPolicy thread running")
        while not self._stop.wait(timeout=self._tick_interval):
            now = self._clock()
            assert self._started_at is not None
            elapsed = now - self._started_at

            # Daily cap takes precedence — once triggered, exit.
            if elapsed >= self._daily_max:
                log.warning(
                    "LongRunPolicy: daily cap reached (%.1f min); stopping all",
                    elapsed / 60.0,
                )
                self._daily_cap_triggered = True
                try:
                    self._scheduler.submit(self._scheduler.stop_all)
                except Exception:  # noqa: BLE001
                    log.exception("LongRunPolicy: scheduler.stop_all submit raised")
                if self._on_daily_cap is not None:
                    try:
                        self._on_daily_cap()
                    except Exception:  # noqa: BLE001
                        log.exception("LongRunPolicy: on_daily_cap_reached raised")
                return

            # Rest cycles: only fire if configured.
            if self._rest_every > 0:
                since_rest = now - (self._last_rest_at or self._started_at)
                if since_rest >= self._rest_every:
                    self._do_rest_cycle()

    def _do_rest_cycle(self) -> None:
        log.info(
            "LongRunPolicy: starting rest cycle of %.1f min",
            self._rest_duration / 60.0,
        )
        try:
            self._scheduler.submit(self._scheduler.pause_all)
        except Exception:  # noqa: BLE001
            log.exception("LongRunPolicy: pause_all submit raised; skipping rest")
            return
        # Wait the rest duration, but respond to stop().
        if self._stop.wait(timeout=self._rest_duration):
            return
        try:
            self._scheduler.submit(self._scheduler.resume_all)
        except Exception:  # noqa: BLE001
            log.exception("LongRunPolicy: resume_all submit raised")
        self._last_rest_at = self._clock()
        log.info("LongRunPolicy: rest cycle complete; running again")


__all__ = ["LongRunPolicy"]
