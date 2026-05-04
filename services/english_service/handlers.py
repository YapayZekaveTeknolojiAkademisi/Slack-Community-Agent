import logging
import re

from packages.slack.client import slack_client
from services.english_service.manager import EnglishService

logger = logging.getLogger(__name__)

english_service = EnglishService()


def handle_service_error(response, client, channel_id):
    if "error" not in response:
        return False

    client.chat_postMessage(
        channel=channel_id,
        text=response["error"]
    )
    return True


def setup_english_handlers():
    app = slack_client.app

    @app.command("/english")
    def start_english(ack, body, client):
        ack()

        user_id = body["user_id"]
        english_service.start_session(user_id)

        client.chat_postMessage(
            channel=body["channel_id"],
            text="Select your level",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Select your level*"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Beginner"},
                            "value": "beginner",
                            "action_id": "english_select_level_beginner"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Intermediate"},
                            "value": "intermediate",
                            "action_id": "english_select_level_intermediate"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Advanced"},
                            "value": "advanced",
                            "action_id": "english_select_level_advanced"
                        }
                    ]
                }
            ]
        )

    @app.message(re.compile(".*"))
    def handle_writing_submission(message, say):
        if message.get("subtype") == "bot_message":
            return

        if "user" not in message:
            return

        user_id = message["user"]
        text = message.get("text", "").strip()

        if not text:
            return

        session = english_service.session_manager.get(user_id)
        if not session:
            return

        if session.step != "waiting_writing":
            return

        logger.debug(
            "English writing submission received. user=%s text_length=%s",
            message.get("user"),
            len(text),
        )

        response = english_service.submit_writing(user_id, text)
        if "error" in response:
            say(response["error"])
            return

        say(response["message"])

    @app.action(re.compile("^english_select_level_"))
    def handle_level_selection(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        selected_level = body["actions"][0]["value"]

        response = english_service.select_level(user_id, selected_level)
        if handle_service_error(response, client, channel_id):
            return

        client.chat_postMessage(
            channel=channel_id,
            text=response["message"],
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Level selected:* `{selected_level}`\nNow choose a mode."
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Writing"},
                            "value": "writing",
                            "action_id": "english_select_mode_writing"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Quiz"},
                            "value": "quiz",
                            "action_id": "english_select_mode_quiz"
                        }
                    ]
                }
            ]
        )

    @app.action(re.compile("^english_select_mode_"))
    def handle_mode_selection(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        selected_mode = body["actions"][0]["value"]

        response = english_service.select_mode(user_id, selected_mode)
        if handle_service_error(response, client, channel_id):
            return

        if response["type"] == "writing_type_selection":
            client.chat_postMessage(
                channel=channel_id,
                text=response["message"],
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Select writing type*"
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Topic Writing"},
                                "value": "topic_writing",
                                "action_id": "english_select_writing_type_topic"
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Translation Writing"},
                                "value": "translation_writing",
                                "action_id": "english_select_writing_type_translation"
                            }
                        ]
                    }
                ]
            )
            return

        if response["type"] == "quiz_question":
            client.chat_postMessage(
                channel=channel_id,
                text=response["message"],
                blocks=build_quiz_blocks(response["message"])
            )
            return

        client.chat_postMessage(
            channel=channel_id,
            text=response["message"]
        )

    @app.action(re.compile("^english_select_writing_type_"))
    def handle_writing_type_selection(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        writing_type = body["actions"][0]["value"]

        response = english_service.select_writing_type(user_id, writing_type)
        if handle_service_error(response, client, channel_id):
            return

        client.chat_postMessage(
            channel=channel_id,
            text=response["message"]
        )

    @app.action(re.compile("^english_quiz_answer_"))
    def handle_quiz_answer(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        selected_answer = body["actions"][0]["value"]

        response = english_service.submit_quiz_answer(user_id, selected_answer)
        if handle_service_error(response, client, channel_id):
            return

        client.chat_postMessage(
            channel=channel_id,
            text=response["message"]
        )

        next_payload = response.get("next")
        if next_payload:
            if next_payload["type"] == "quiz_question":
                client.chat_postMessage(
                    channel=channel_id,
                    text=next_payload["message"],
                    blocks=build_quiz_blocks(next_payload["message"])
                )
            else:
                client.chat_postMessage(
                    channel=channel_id,
                    text=next_payload["message"]
                )


def build_quiz_blocks(message: str):
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "1"},
                    "value": "1",
                    "action_id": "english_quiz_answer_1"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "2"},
                    "value": "2",
                    "action_id": "english_quiz_answer_2"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "3"},
                    "value": "3",
                    "action_id": "english_quiz_answer_3"
                }
            ]
        }
    ]