"""Structured logging for the server process.

One place that owns log formatting so a deployed kiosk emits parseable,
timestamped lines (systemd/journald or a log file) instead of bare uvicorn
defaults. Idempotent: safe to call again under `--reload`.
"""

from __future__ import annotations

import logging
import sys

_FMT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # uvicorn's own access log duplicates our request middleware; quiet it so the
    # server layer speaks with one voice.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
