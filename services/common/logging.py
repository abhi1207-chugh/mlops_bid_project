"""Structured JSON logs. Every line carries correlation_id (= run_id) when one is bound."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id.get(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_bid_json", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._bid_json = True  # type: ignore[attr-defined]
    root.handlers = [handler]
    root.setLevel(level)


def log(logger: logging.Logger, message: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, message, extra={"fields": fields})
