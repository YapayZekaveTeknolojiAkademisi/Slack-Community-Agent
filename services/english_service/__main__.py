"""
English Service — Entry Point

Başlatma sırası (summary ile aynı model):
  1. Logger (import sırasında)
  2. Bolt handler kayıtları (`setup_english_handlers`)
  3. SIGINT/SIGTERM → `stop` olayı
  4. Slack Socket `connect()` (`start()` sonsuz blok yok)
  5. Ana thread `stop.wait()` → `finally` içinde `close_socket_mode_safe`

Not: `challenge_service` aynı process içinde Socket açarsa english handler’lar orada da
yüklenmiş olur (`setup_english_handlers`). Bu süreçleri **aynı Slack app token ile aynı
anda** iki kez bağlamak genelde doğru değildir; tek Socket yeterlidir.
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

from services.english_service.logger import _logger  # noqa: F401 — start_logging
from services.english_service.handlers import setup_english_handlers
from packages.slack.community_help import setup_community_help_command

_SERVICE = "[English Service]"


def main() -> None:
    setup_english_handlers()
    setup_community_help_command()

    stop = threading.Event()
    install_stop_signals(stop, _logger, _SERVICE)

    _logger.info("%s Phase 1/2: Slack command/message handlers registered", _SERVICE)

    try:
        connect_socket_mode(slack_client.socket_handler, _logger, _SERVICE)
        _logger.info("%s Phase 2/2: Running — send SIGINT or SIGTERM to stop", _SERVICE)
        stop.wait()
    except Exception as exc:
        _logger.critical("%s Socket Mode failed: %s", _SERVICE, exc, exc_info=True)
        sys.exit(1)
    finally:
        close_socket_mode_safe(slack_client.socket_handler, _logger, _SERVICE)
        _logger.info("%s Exited cleanly", _SERVICE)


if __name__ == "__main__":
    main()
