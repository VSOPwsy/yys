"""
Centralized logging setup.

Public surface:
    setup_logging(account_id=None, level=logging.INFO) -> None
    get_logger(name: str) -> logging.Logger

`setup_logging` is idempotent and configures:
  * a colored stream handler on stdout,
  * a `TimedRotatingFileHandler` at ``logs/[<account_id>/]bot_YYYY-MM-DD.log``.

Idempotency matters because Alas's `vendor.alas.module.logger` import has side
effects (it installs its own handlers and prints a START banner). We call
`setup_logging` before any Alas import we cannot avoid, so we own the root.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"

_SETUP_LOCK = threading.Lock()
_SETUP_DONE = False


# ANSI escape codes. Windows 10+ terminals support them natively when the
# console is in VT mode, which Python enables for stdout on import on recent
# CPython builds. Fallback: garbage characters in old `cmd.exe`; acceptable.
_RESET = "\033[0m"
_LEVEL_COLOR = {
    logging.DEBUG: "\033[36m",      # cyan
    logging.INFO: "\033[32m",       # green
    logging.WARNING: "\033[33m",    # yellow
    logging.ERROR: "\033[31m",      # red
    logging.CRITICAL: "\033[1;31m", # bold red
}


class _ColorFormatter(logging.Formatter):
    """Colorize only the levelname column, not the whole line.

    Coloring the whole line trips up log aggregators that try to parse the
    timestamp.
    """

    def __init__(self, fmt: str, datefmt: Optional[str], use_color: bool) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self._use_color:
            color = _LEVEL_COLOR.get(record.levelno, "")
            record.levelname = f"{color}{record.levelname:<8}{_RESET}"
        else:
            record.levelname = f"{record.levelname:<8}"
        return super().format(record)


def _stdout_supports_color() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return True


def setup_logging(
    account_id: Optional[str] = None,
    level: int = logging.INFO,
    log_dir: Optional[Path] = None,
) -> Path:
    """Wire up root logger handlers. Idempotent.

    Args:
        account_id: If provided, file logs go under ``logs/<account_id>/``.
            Multi-account safety: each account's log stream is physically
            separated. If None, logs go directly under ``logs/``.
        level: Logging threshold for the root logger.
        log_dir: Override the on-disk log root. Defaults to ``<project>/logs``.
            Used by tests.

    Returns:
        The directory where log files will be written.

    Raises:
        OSError: If the log directory cannot be created.
    """
    global _SETUP_DONE

    with _SETUP_LOCK:
        root = logging.getLogger()
        root.setLevel(level)

        target_dir = (log_dir or _LOG_DIR)
        if account_id:
            target_dir = target_dir / account_id
        target_dir.mkdir(parents=True, exist_ok=True)

        # Tear down any handlers we previously installed so re-calls with a
        # new account_id rewire the file destination cleanly. We tag handlers
        # we own with a private attribute so we don't trample handlers that
        # vendor code (Alas) may have installed.
        for handler in list(root.handlers):
            if getattr(handler, "_yys_owned", False):
                root.removeHandler(handler)
                handler.close()

        fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        datefmt = "%Y-%m-%d %H:%M:%S"

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(
            _ColorFormatter(fmt, datefmt, use_color=_stdout_supports_color())
        )
        console._yys_owned = True  # type: ignore[attr-defined]
        root.addHandler(console)

        file_path = target_dir / "bot.log"
        file_handler = TimedRotatingFileHandler(
            filename=str(file_path),
            when="midnight",
            backupCount=14,
            encoding="utf-8",
            utc=False,
        )
        # Date suffix on rotated files (bot.log -> bot.log.2026-05-14).
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(_ColorFormatter(fmt, datefmt, use_color=False))
        file_handler._yys_owned = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

        _SETUP_DONE = True
        return target_dir


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger.

    Args:
        name: Conventionally ``__name__`` from the calling module. Becomes the
            ``%(name)s`` field in log records, letting readers tell vision
            warnings apart from input-backend warnings.

    Returns:
        A `logging.Logger`. Auto-calls `setup_logging()` with defaults on
        first use so importing a module before `main.py` has run doesn't lose
        log records.
    """
    if not _SETUP_DONE:
        setup_logging()
    return logging.getLogger(name)
