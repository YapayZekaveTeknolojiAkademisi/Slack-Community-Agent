"""Modal submit ve buton action handler'ları."""

import logging

from packages.database.manager import db
from packages.settings import get_settings
from packages.slack.blocks.layouts import Layouts
from packages.slack.client import slack_client
from services.feature_request_service.core.event_loop import run_async
from services.feature_request_service.service import FeatureRequestService
from services.feature_request_service.utils.notifications import (
    NotificationType,
    send_notification,
)

logger = logging.getLogger("feature_request_service.handlers.events")
app = slack_client.app
_service = None


def _svc():
    global _service
    if _service is None:
        _service = FeatureRequestService(db)
    return _service


@app.view("feature_request_modal")
def handle_submit(ack, body, client):
    ack()
    uid = body["user"]["id"]
    channel_id = body["view"].get("private_metadata", "")
    if not channel_id:
        channel_id = get_settings().slack_command_channels[0]

    raw = body["view"]["state"]["values"]["feature_input_block"]["feature_text_input"][
        "value"
    ]
    try:
        r = run_async(_svc().submit_request(uid, raw))
    except Exception as e:
        logger.error(f"Submit hatası: {e}", exc_info=True)
        send_notification(
            client, uid, channel_id, NotificationType.ACTION_RESULT, "❌ Teknik hata."
        )
        return
    match r.get("status"):
        case "created":
            send_notification(
                client,
                uid,
                channel_id,
                NotificationType.ACTION_RESULT,
                "Kaydedildi!",
                Layouts.feature_request_success(raw),
            )
        case "similar_found":
            send_notification(
                client,
                uid,
                channel_id,
                NotificationType.ACTION_RESULT,
                "Benzer var.",
                Layouts.feature_request_similar(
                    r["existing_text"], r["existing_id"], r["pending_id"]
                ),
            )
        case "exact_match":
            send_notification(
                client,
                uid,
                channel_id,
                NotificationType.ACTION_RESULT,
                "Çok benzer talep.",
                Layouts.feature_request_exact_match(
                    r["existing_text"], r["existing_id"]
                ),
            )
        case "quota_exceeded":
            send_notification(
                client,
                uid,
                channel_id,
                NotificationType.ACTION_RESULT,
                "Hak doldu.",
                Layouts.feature_request_quota_exceeded(r["used"], r["max"]),
            )


@app.view("feature_request_edit_modal")
def handle_edit_submit(ack, body, client):
    ack()
    uid = body["user"]["id"]
    metadata = body["view"].get("private_metadata", "")
    parts = metadata.split("|")
    rid = parts[0]
    channel_id = parts[1] if len(parts) > 1 else ""
    if not channel_id:
        channel_id = get_settings().slack_command_channels[0]

    txt = body["view"]["state"]["values"]["feature_input_block"]["feature_text_input"][
        "value"
    ]
    try:
        run_async(_svc().update_request(rid, txt))
        send_notification(
            client,
            uid,
            channel_id,
            NotificationType.ACTION_RESULT,
            "Güncellendi!",
            Layouts.feature_request_success(txt),
        )
    except Exception as e:
        logger.error(f"Edit hatası: {e}", exc_info=True)
        send_notification(
            client,
            uid,
            channel_id,
            NotificationType.ACTION_RESULT,
            "❌ Güncelleme hatası.",
        )


@app.action("feature_edit_yes")
def handle_edit_yes(ack, body, client, respond):
    ack()
    action_value = body["actions"][0]["value"]
    # value is formatted as "existing_id|pending_id" or just existing_id for old formats
    parts = action_value.split("|")
    rid = parts[0]
    channel_id = body.get("channel", {}).get("id", "")
    try:
        txt = run_async(_svc().get_request_text(rid))
        client.views_open(
            trigger_id=body["trigger_id"],
            view=Layouts.feature_request_edit_modal(txt, rid, channel_id),
        )
        # Mesajdaki butonları pasifleştir (ephemeral mesaj uçar)
        respond(
            text="✏️ Fikrinizi düzenlemek için çıkan pencereyi kullanabilirsiniz.",
            replace_original=True,
        )
    except Exception as e:
        logger.error(f"Edit modal hatası: {e}", exc_info=True)


@app.action("feature_edit_no")
def handle_edit_no(ack, body, client, respond):
    ack()
    uid = body["user"]["id"]
    channel_id = body.get("channel", {}).get("id", "")
    if not channel_id:
        channel_id = get_settings().slack_command_channels[0]

    pending_id = body["actions"][0]["value"]

    try:
        if pending_id and pending_id != "ignore":
            result = run_async(_svc().approve_pending_request(pending_id))
            if result.get("status") in ("approved", "invalid_status"):
                respond(
                    text="✅ Yeni fikriniz sisteme kaydedildi! Teşekkürler.",
                    replace_original=True,
                )
            else:
                respond(
                    text="❌ İşlem yapılamadı. Tekrar deneyiniz.", replace_original=True
                )
        else:
            respond(
                text="💡 Tamam! `/cemilimyapar` komutu ile yeni fikir gönderebilirsin.",
                replace_original=True,
            )
    except Exception as e:
        logger.error(f"Approve pending hatası: {e}", exc_info=True)
        respond(
            text="❌ İşlem sırasında teknik bir hata oluştu.", replace_original=True
        )


@app.action("feature_edit_cancel")
def handle_edit_cancel(ack, body, client, respond):
    ack()
    uid = body["user"]["id"]
    channel_id = body.get("channel", {}).get("id", "")

    # Kullanıcıya nötr mesaj göndererek butonları yok et
    respond(
        text="🛑 İşlem iptal edildi. Yeni fikirlerinizi bekliyoruz!",
        replace_original=True,
    )
