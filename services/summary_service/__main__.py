"""
Summary Service — Entry Point

Başlatma sırası:
  1. Logger
  2. SIGINT/SIGTERM → `stop` olayı (minimal sinyal işleyici)
  3. Bolt handler kayıtları (import)
  4. Slack Socket Mode `connect()` (blocking değil — `start()` yerine)
  5. Ana thread `stop.wait()` — sinyal gelince `close()` + çıkış

Kapanış:
  - `socket_handler.close()` (WebSocket + işçiler)
  - Aynı yaşam döngüsü `packages.slack.socket_runtime` ile challenge ile hizalanır.
"""
from __future__ import annotations

import sys
import threading

from packages.slack.client import slack_client
from packages.slack.socket_runtime import (
    close_socket_mode_safe,
    connect_socket_mode,
    install_stop_signals,
)

from services.summary_service import handlers as _handlers  # noqa: F401 — handler kaydı
from services.summary_service.logger import _logger  # noqa: F401 — start_logging

_SERVICE = "[Summary Service]"


def main() -> None:
    stop = threading.Event()
    install_stop_signals(stop, _logger, _SERVICE)

    _logger.info("%s Phase 1/3: Logger initialized", _SERVICE)
    _logger.info("%s Phase 2/3: Slack command handlers registered", _SERVICE)

    try:
        connect_socket_mode(slack_client.socket_handler, _logger, _SERVICE)
        _logger.info("%s Phase 3/3: Running — send SIGINT or SIGTERM to stop", _SERVICE)
        stop.wait()
    except Exception as exc:
        _logger.critical("%s Socket Mode failed: %s", _SERVICE, exc, exc_info=True)
        sys.exit(1)
    finally:
        _logger.info("%s Shutting down...", _SERVICE)
        close_socket_mode_safe(slack_client.socket_handler, _logger, _SERVICE)
        _logger.info("%s Exited cleanly", _SERVICE)


if __name__ == "__main__":
    main()
