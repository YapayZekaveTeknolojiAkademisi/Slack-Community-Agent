"""
This Month Service — Entry Point

Kullanim:
  python -m services.this_month_service
"""
from services.this_month_service.logger import _logger  # noqa: F401 — logging baslatilir
from packages.slack.client import slack_client
from services.this_month_service import handlers as _handlers  # noqa: F401 — handler kayitlari aktive edilir


def main():
    _logger.info("[This Month Service] Handlers registered.")
    _logger.info("[This Month Service] Starting Slack Socket Mode...")
    slack_client.socket_handler.start()


if __name__ == "__main__":
    main()
