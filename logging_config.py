"""
Central logging setup for web (run.py / gunicorn) and CLI-style entrypoints.

Environment:
  LOG_LEVEL           INFO, DEBUG, WARNING (default INFO)
  LOG_FORMAT          text | json (default text)
  LOG_FILE            path for rotating file log (default fraud_detection.log)
  LOG_TO_STDOUT_ONLY  if 1/true, skip file handler (useful in some containers)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


class JsonFormatter(logging.Formatter):
    """One JSON object per line for simple log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_CONFIGURED = False


def reset_logging_config() -> None:
    """Clear root handlers and allow ``configure_logging`` to run again (tests)."""
    global _CONFIGURED
    _CONFIGURED = False
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


def configure_logging(service_name: str = "fraud-detection") -> None:
    """Configure root logging once (safe to call from run.py and wsgi)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger()
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))

    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = (os.environ.get("LOG_FORMAT") or "text").lower().strip()
    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

    stdout_only = os.environ.get("LOG_TO_STDOUT_ONLY", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if not stdout_only:
        log_path = os.environ.get("LOG_FILE", "fraud_detection.log")
        try:
            fh = RotatingFileHandler(
                log_path,
                maxBytes=int(os.environ.get("LOG_MAX_BYTES", "10000000")),
                backupCount=int(os.environ.get("LOG_BACKUP_COUNT", "5")),
                encoding="utf-8",
            )
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except OSError as e:
            logging.basicConfig(level=root.level)
            logging.getLogger(__name__).warning(
                "Could not open log file %s (%s); logging to stdout only",
                log_path,
                e,
            )

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    logging.getLogger(__name__).debug("Logging configured (service=%s)", service_name)
