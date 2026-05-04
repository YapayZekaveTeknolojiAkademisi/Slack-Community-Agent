"""
Summary Service — Entry Point

Başlatma sırası:
  1. Logger başlat
  2. Handler'ları kayıt et (@app.command + @app.action dekoratörleri)
  3. Slack Socket Mode başlat (blocking)
  4. SIGINT/SIGTERM → graceful shutdown
"""
from __future__ import annotations

import signal
import sys

from services.summary_service.logger import _logger  # noqa: F401 — start_logging (once)
from packages.slack.client import slack_client
from services.summary_service import handlers as _handlers  # noqa: F401


def _handle_signal(sig: int, _frame) -> None:
    _logger.info(
        "[Summary Service] Signal %s received, shutting down...",
        signal.Signals(sig).name,
    )
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("[Summary Service] Handlers registered")

    # Slack Socket Mode başlat (blocking)
    _logger.info("[Summary Service] Starting Slack Socket Mode...")
    try:
        slack_client.socket_handler.start()
    except Exception as exc:
        _logger.critical("[Summary Service] Socket Mode failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()