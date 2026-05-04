from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.logger.manager import get_logger, start_logging

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "event_service"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

EVENT_SERVICE_LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "system": {
            "()": "packages.logger.formatters.SystemMessageFormatter",
        },
        "error_json": {
            "()": "packages.logger.formatters.ErrorMessageFormatter",
        },
    },
    "filters": {
        "system_only": {
            "()": "packages.logger.filters.SystemFilter",
        },
        "errors_only": {
            "()": "packages.logger.filters.ErrorFilter",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "system",
            "filters": ["system_only"],
            "stream": "ext://sys.stdout",
        },
        "console": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "system",
            "filters": ["system_only"],
            "filename": str(_LOG_DIR / "system.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "errors": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": "error_json",
            "filters": ["errors_only"],
            "filename": str(_LOG_DIR / "errors.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["stdout", "console", "errors"],
    },
}

start_logging(EVENT_SERVICE_LOGGING)
_logger = get_logger("event_service")

__all__ = ["_logger"]
