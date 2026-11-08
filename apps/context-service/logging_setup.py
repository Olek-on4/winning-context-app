"""One log line shape for the whole service, and one place that decides where it goes.

`2026-11-08T01:51:33.622Z [INFO] etyt.index: embedded 897/897`

The tag is the module doing the work (`index`, `load`, `extract`, `api`, `planner`,
`retrieval`), so a tail of the log reads as a sequence of steps rather than as prose.

Machine output (the JSON line each CLI command prints) stays on stdout; logs go to stderr,
and to a file when `ETYT_LOG_FILE` is set, so `cli index > out.json 2> run.log` and
`ETYT_LOG_FILE=run.log cli index` both work without a shell trick. Level is
`ETYT_LOG_LEVEL` (`debug`, `info`, `warning`, `error`).
"""

from __future__ import annotations

import logging
import os
import sys
import time

FORMAT = "%(asctime)s.%(msecs)03dZ [%(levelname)s] %(name)s: %(message)s"
DATE = "%Y-%m-%dT%H:%M:%S"
LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_configured = False


def configure(level: str | None = None, path: str | None = None) -> None:
    """Idempotent: re-configuring replaces handlers instead of stacking them."""
    global _configured
    name = (level or os.getenv("ETYT_LOG_LEVEL") or "info").strip().lower()
    target = path if path is not None else os.getenv("ETYT_LOG_FILE")

    root = logging.getLogger("etyt")
    root.setLevel(LEVELS.get(name, logging.INFO))
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(FORMAT, datefmt=DATE)
    formatter.converter = time.gmtime  # one clock for every line, whatever the locale
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if target:
        try:
            handle = logging.FileHandler(target, encoding="utf-8")
            handle.setFormatter(formatter)
            root.addHandler(handle)
        except OSError as exc:  # an unwritable path must not stop the work
            root.warning("could not open %s (%s); logging to stderr only", target, exc)
    _configured = True


def logger(tag: str) -> logging.Logger:
    """A namespaced logger; `configure()` runs once, lazily, on first use."""
    if not _configured:
        configure()
    return logging.getLogger(f"etyt.{tag}")


def request_logger():
    """One line per request with its duration; uvicorn's access log is off in `cli serve`."""
    log = logger("api")

    async def middleware(request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.error(
                "%s %s failed after %.0fms",
                request.method,
                request.url.path,
                (time.perf_counter() - started) * 1000,
            )
            raise
        elapsed = (time.perf_counter() - started) * 1000
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        log.log(
            level,
            "%s %s -> %s in %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
        return response

    return middleware
