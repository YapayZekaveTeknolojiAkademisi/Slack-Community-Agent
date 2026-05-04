from __future__ import annotations

import logging


class SystemFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            getattr(record, "api", False)
            or getattr(record, "queue", False)
            or getattr(record, "clustering", False)
        )


class ErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


class ApiFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return bool(getattr(record, "api", False))


class QueueFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return bool(getattr(record, "queue", False))


class ClusteringFilter(logging.Filter):
    """Yalnızca extra={"clustering": ...} içeren kayıtları geçirir."""
    def filter(self, record: logging.LogRecord) -> bool:
        return bool(getattr(record, "clustering", False))