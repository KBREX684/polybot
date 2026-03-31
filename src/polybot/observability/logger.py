from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog


def _redact_sensitive(logger_name: str, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Processor to redact sensitive fields like API keys."""
    sensitive_keys = {"api_key", "secret", "token", "password", "authorization"}
    for key in list(event_dict.keys()):
        if isinstance(key, str) and key.lower() in sensitive_keys:
            event_dict[key] = "***REDACTED***"
        elif isinstance(event_dict[key], str) and len(event_dict[key]) > 40:
            # Truncate very long values (likely full API responses)
            pass
    return event_dict


def _add_timestamp(logger_name: str, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    if "timestamp" not in event_dict:
        event_dict["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
    return event_dict


def configure_logging(log_path: str = "logs/polybot.jsonl", log_level: str = "INFO") -> None:
    """Configure structlog for JSON logging to file + console."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _add_timestamp,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive,
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level, logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also write to file
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        root_logger.addHandler(file_handler)


def get_logger(name: str = "polybot") -> Any:
    return structlog.get_logger(name)
