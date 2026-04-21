from packages.slack.client import slack_client
from services.english_service.manager import EnglishService
import re

english_service = EnglishService()


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
        user_id = message["user"]
        text = message.get("text", "").strip()

        session = english_service.session_manager.get(user_id)
        if not session:
            return

        if session.step != "waiting_writing":
            return

        print("MESSAGE HANDLER CALLED")
        print("user:", message.get("user"))
        print("text:", message.get("text"))
        response = english_service.submit_writing(user_id, text)
        say(response["message"])

    @app.action(re.compile("^english_select_level_"))
    def handle_level_selection(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        selected_level = body["actions"][0]["value"]

        response = english_service.select_level(user_id, selected_level)

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

        # Writing mode önce subtype seçtirecek
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

        # Quiz mode doğrudan ilk soruyu döndürüyor
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