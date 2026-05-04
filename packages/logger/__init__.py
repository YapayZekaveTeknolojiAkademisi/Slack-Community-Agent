"""Merkezi loglama: servis girişinde ``start_logging(dictConfig)``, sonra ``get_logger(name)``."""

from packages.logger.manager import get_logger, start_logging, stop_logging

__all__ = ["get_logger", "start_logging", "stop_logging"]
