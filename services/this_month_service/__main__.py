from __future__ import annotations

import signal
import sys

from services.this_month_service.logger import _logger
from packages.slack.client import slack_client
from services.this_month_service import handlers as _handlers  # noqa: F401


def _handle_signal(sig: int, _frame) -> None:
    _logger.info(
        "[This Month Service] Signal %s received, shutting down...",
        signal.Signals(sig).name,
    )
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("[This Month Service] Handlers registered.")

    # Slack Socket Mode başlat (blocking)
    _logger.info("[This Month Service] Starting Slack Socket Mode...")
    try:
        slack_client.socket_handler.start()
    except Exception as exc:
        _logger.critical("[This Month Service] Socket Mode failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
