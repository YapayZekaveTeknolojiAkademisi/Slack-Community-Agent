from __future__ import annotations
import logging
import json
from datetime import datetime
import traceback


level_formatters = {
    logging.DEBUG: "[>]",
    logging.INFO: "[i]",
    logging.WARNING: "[*]",
    logging.ERROR: "[X]",
    logging.CRITICAL: "[!]",
}


# ---- BASE FORMATTER -----------------------------------------------------
class BaseFormatter(logging.Formatter):
    def timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---- SYSTEM MESSAGE FORMATTER --------------------------------------------
class SystemMessageFormatter(BaseFormatter):
    def format(self, record: logging.LogRecord) -> str:
        level_icon = level_formatters.get(record.levelno, "[?]")
        return f"{self.timestamp()} {level_icon} {record.getMessage()}"


# ---- ERROR MESSAGE FORMATTER --------------------------------------------
class ErrorMessageFormatter(BaseFormatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.timestamp(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        if record.exc_info:
            exc_cls = record.exc_info[0]
            exc_type = exc_cls.__name__ if exc_cls is not None else "NoneType"
            exc_msg = str(record.exc_info[1])
            
            # Location info: file / function / line
            tb = traceback.extract_tb(record.exc_info[2])
            locations = [
                {"file": frame.filename, "function": frame.name, "line": frame.lineno}
                for frame in tb
            ]

            log_record["location"] = locations
            log_record["exception"] = {
                "type": exc_type,
                "message": exc_msg
            }

        return json.dumps(log_record, ensure_ascii=False, indent=2)


# ---- API MESSAGE FORMATTER ----------------------------------------------
class ApiMessageFormatter(BaseFormatter):
    def format(self, record: logging.LogRecord) -> str:
        api_extra = getattr(record, "api", {})
        type = api_extra.get("TYPE", "-")
        route = api_extra.get("Route", "-")
        status = api_extra.get("status", "-")
        time_taken = api_extra.get("time", "-")
        return f"{type} --> {route} ({status}) ({time_taken})"


# ---- QUEUE MESSAGE FORMATTER --------------------------------------------
class QueueMessageFormatter(BaseFormatter):
    def format(self, record: logging.LogRecord) -> str:
        queue_extra = getattr(record, "queue", {})
        name = queue_extra.get("name", "-")
        size = queue_extra.get("size", "-")
        action = queue_extra.get("action", "-")
        value = queue_extra.get("value", "-")
        return f"{name} ({size}) -- {action} -- {value}"


# ---- CLUSTERING FORMATTER -----------------------------------------------
class ClusteringFormatter(BaseFormatter):
    """Her clustering çalışmasını tek satır JSON olarak yazar.

    Kullanım:
        logger.info("run", extra={"clustering": {...clustering_log dict...}})
    """
    def format(self, record: logging.LogRecord) -> str:
        data = getattr(record, "clustering", {})
        return json.dumps(data, ensure_ascii=False, default=str)