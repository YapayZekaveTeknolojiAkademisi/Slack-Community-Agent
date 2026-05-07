import re

from slack_sdk.errors import SlackApiError

from packages.slack.client import slack_client
from services.english_service.logger import _logger
from services.english_service.manager import EnglishService

english_service = EnglishService()


def _post_public_channel_announcement(client, channel_id: str, text: str, blocks: list | None = None) -> None:
    """Genel bildirim veya herkese görünür tespit — yalnızca kanal geneline yönelik mesajlar için kullanın."""
    kwargs: dict = {"channel": channel_id, "text": text or " "}
    if blocks:
        kwargs["blocks"] = blocks
    client.chat_postMessage(**kwargs)


def _post_user_reply(
    client,
    channel_id: str,
    user_id: str,
    text: str,
    blocks: list | None = None,
) -> None:
    """Öğrenciye özel içerik — ephemeral; kanal arşivliyse veya ephemeral mümkün değilse DM."""
    kwargs: dict = {"channel": channel_id, "user": user_id, "text": text or " "}
    if blocks:
        kwargs["blocks"] = blocks
    try:
        client.chat_postEphemeral(**kwargs)
    except SlackApiError as exc:
        err = exc.response.get("error") if exc.response else None
        if err not in ("is_archived", "channel_not_found", "not_in_channel"):
            raise
        _logger.warning(
            "English ephemeral başarısız (%s) — DM ile gönderiliyor user=%s",
            err,
            user_id,
        )
        try:
            dm = client.conversations_open(users=user_id)["channel"]["id"]
            dm_kw: dict = {"channel": dm, "text": text or " "}
            if blocks:
                dm_kw["blocks"] = blocks
            client.chat_postMessage(**dm_kw)
        except Exception as dm_exc:
            _logger.error("English DM fallback başarısız user=%s: %s", user_id, dm_exc)


def handle_service_error(response, client, channel_id: str, user_id: str):
    if response.get("error"):
        _post_user_reply(client, channel_id, user_id, str(response.get("error")))
        return True
    if response.get("type") == "quiz_error":
        _post_user_reply(
            client,
            channel_id,
            user_id,
            response.get("message", "Quiz error. Please start over with `/english`."),
        )
        return True
    return False


def setup_english_handlers():
    app = slack_client.app

    @app.command("/english")
    def start_english(ack, body, client):
        ack()

        user_id = body["user_id"]
        channel_id = body["channel_id"]
        english_service.start_session(user_id)

        _post_user_reply(
            client,
            channel_id,
            user_id,
            text="Select your level",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Select your level*",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Beginner"},
                            "value": "beginner",
                            "action_id": "english_select_level_beginner",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Intermediate"},
                            "value": "intermediate",
                            "action_id": "english_select_level_intermediate",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Advanced"},
                            "value": "advanced",
                            "action_id": "english_select_level_advanced",
                        },
                    ],
                },
            ],
        )

    @app.message(re.compile(".*"))
    def handle_writing_submission(message, client):
        # Yalnızca düz kullanıcı mesajları yazı teslimidir; bot / düzenleme / ek dosya vb.
        # tetiklemelerinde LLM veya ephemeral gönderilmez (Slack yanlış event tekrarı riski azalır).
        if message.get("subtype"):
            return

        if "user" not in message:
            return

        user_id = message["user"]
        channel_id = message.get("channel") or message.get("channel_id")
        text = message.get("text", "").strip()

        if not text or not channel_id:
            return

        if text.startswith("/"):
            return

        session = english_service.session_manager.get(user_id)
        if not session:
            return

        if session.step != "waiting_writing":
            return

        _logger.debug(
            "English writing submission received. user=%s text_length=%s",
            message.get("user"),
            len(text),
        )

        try:
            response = english_service.submit_writing(user_id, text)
        except Exception as exc:
            _logger.error("English submit_writing failed user=%s: %s", user_id, exc, exc_info=True)
            _post_user_reply(
                client,
                channel_id,
                user_id,
                "Evaluation failed unexpectedly. Please try again or restart with `/english`.",
            )
            return

        if "error" in response:
            _post_user_reply(client, channel_id, user_id, str(response.get("error")))
            return

        _post_user_reply(
            client,
            channel_id,
            user_id,
            response.get("message", "No feedback returned. Try again."),
        )

    @app.action(re.compile("^english_select_level_"))
    def handle_level_selection(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        selected_level = body["actions"][0]["value"]

        response = english_service.select_level(user_id, selected_level)
        if handle_service_error(response, client, channel_id, user_id):
            return

        _post_user_reply(
            client,
            channel_id,
            user_id,
            text=response.get("message", ""),
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Level selected:* `{selected_level}`\nNow choose a mode.",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Writing"},
                            "value": "writing",
                            "action_id": "english_select_mode_writing",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Quiz"},
                            "value": "quiz",
                            "action_id": "english_select_mode_quiz",
                        },
                    ],
                },
            ],
        )

    @app.action(re.compile("^english_select_mode_"))
    def handle_mode_selection(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        selected_mode = body["actions"][0]["value"]

        response = english_service.select_mode(user_id, selected_mode)
        if handle_service_error(response, client, channel_id, user_id):
            return

        rtype = response.get("type")
        if rtype == "writing_type_selection":
            _post_user_reply(
                client,
                channel_id,
                user_id,
                text=response.get("message", ""),
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Select writing type*",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Topic Writing"},
                                "value": "topic_writing",
                                "action_id": "english_select_writing_type_topic",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Translation Writing"},
                                "value": "translation_writing",
                                "action_id": "english_select_writing_type_translation",
                            },
                        ],
                    },
                ],
            )
            return

        if rtype == "quiz_question":
            qmsg = response.get("message", "")
            _post_user_reply(
                client,
                channel_id,
                user_id,
                text=qmsg,
                blocks=build_quiz_blocks(qmsg),
            )
            return

        _post_user_reply(
            client,
            channel_id,
            user_id,
            response.get("message", "Something went wrong. Try `/english` again."),
        )

    @app.action(re.compile("^english_select_writing_type_"))
    def handle_writing_type_selection(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        writing_type = body["actions"][0]["value"]

        response = english_service.select_writing_type(user_id, writing_type)
        if handle_service_error(response, client, channel_id, user_id):
            return

        _post_user_reply(
            client,
            channel_id,
            user_id,
            response.get("message", "No task returned. Try `/english` again."),
        )

    @app.action(re.compile("^english_quiz_answer_"))
    def handle_quiz_answer(ack, body, client):
        ack()

        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        selected_answer = body["actions"][0]["value"]

        response = english_service.submit_quiz_answer(user_id, selected_answer)
        if handle_service_error(response, client, channel_id, user_id):
            return

        _post_user_reply(
            client,
            channel_id,
            user_id,
            response.get("message", ""),
        )

        next_payload = response.get("next")
        if next_payload:
            ntype = next_payload.get("type")
            if ntype == "quiz_question":
                nmsg = next_payload.get("message", "")
                _post_user_reply(
                    client,
                    channel_id,
                    user_id,
                    text=nmsg,
                    blocks=build_quiz_blocks(nmsg),
                )
            else:
                _post_user_reply(
                    client,
                    channel_id,
                    user_id,
                    next_payload.get("message", ""),
                )


def build_quiz_blocks(message: str):
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message,
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "1"},
                    "value": "1",
                    "action_id": "english_quiz_answer_1",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "2"},
                    "value": "2",
                    "action_id": "english_quiz_answer_2",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "3"},
                    "value": "3",
                    "action_id": "english_quiz_answer_3",
                },
            ],
        },
    ]
