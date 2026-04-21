from services.english_service.handlers import setup_english_handlers
from packages.slack.client import slack_client


def main():
    setup_english_handlers()
    print("English service handlers registered.")
    print("Starting Slack Socket Mode for English service...")
    slack_client.socket_handler.start()


if __name__ == "__main__":
    main()