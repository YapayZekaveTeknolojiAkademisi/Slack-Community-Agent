from services.english_service.logger import _logger  # noqa: F401 — start_logging (once)
from packages.slack.client import slack_client
from services.english_service.handlers import setup_english_handlers


def main():
    setup_english_handlers()
    _logger.info("English service handlers registered.")
    _logger.info("Starting Slack Socket Mode for English service...")
    slack_client.socket_handler.start()


if __name__ == "__main__":
    main()