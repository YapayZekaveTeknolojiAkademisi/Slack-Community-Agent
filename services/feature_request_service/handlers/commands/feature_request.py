"""
/cemilimyapar ve /cemil-report slash komut handler'ları.
"""

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

logger = logging.getLogger("feature_request_service.handlers.commands")
app = slack_client.app
_service = None


def _svc():
    global _service
    if _service is None:
        _service = FeatureRequestService(db)
    return _service


@app.command("/cemilimyapar")
def handle_cemilimyapar(ack, body, client):
    ack()
    channel_id = body.get("channel_id", "")
    client.views_open(
        trigger_id=body["trigger_id"],
        view=Layouts.feature_request_modal(channel_id=channel_id),
    )


@app.command("/cemil-report")
def handle_cemil_report(ack, body, client):
    ack()
    uid = body["user_id"]
    txt = body.get("text", "").strip()
    s = get_settings()
    admins = s.slack_admins
    if uid not in admins:
        send_notification(
            client,
            uid,
            uid,
            NotificationType.COMMAND_ERROR,
            "❌ Bu komut sadece adminler içindir.",
        )
        return
    if txt.startswith("cluster-details"):
        parts = txt.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_notification(
                client,
                uid,
                uid,
                NotificationType.COMMAND_ERROR,
                "Geçersiz ID! Kullanım: `/cemil-report cluster-details <id>`",
            )
            return

        cluster_id = int(parts[1])
        try:
            details = run_async(_svc().get_cluster_details(cluster_id))
            blocks = Layouts.feature_cluster_details(
                details["cluster_id"], details["label"], details["requests"]
            )
            send_notification(
                client,
                uid,
                uid,
                NotificationType.SYSTEM_REPORT,
                "Cluster Detayları",
                blocks,
            )
        except Exception as e:
            logger.error(f"Cluster detay hatası: {e}", exc_info=True)
            send_notification(
                client,
                uid,
                uid,
                NotificationType.COMMAND_ERROR,
                "❌ Cluster detayı alınamadı.",
            )
        return

    if txt != "feature-requests":
        send_notification(
            client,
            uid,
            uid,
            NotificationType.COMMAND_ERROR,
            f"Bilinmeyen: `{txt}`\nKullanım: `/cemil-report feature-requests` veya `/cemil-report cluster-details <id>`",
        )
        return
    try:
        r_data = run_async(_svc().run_clustering_pipeline(is_preview=True))
        rt = run_async(
            _svc().generate_admin_report(
                pipeline_stats=r_data.get("clustering_log"),
                is_preview=True,
                preview_data=r_data,
            )
        )
        blocks = Layouts.feature_request_report(rt)
        send_notification(
            client,
            uid,
            uid,
            NotificationType.SYSTEM_REPORT,
            "Rapor",
            blocks,
        )
    except Exception as e:
        logger.error(f"Rapor hatası: {e}", exc_info=True)
        send_notification(
            client, uid, uid, NotificationType.COMMAND_ERROR, "❌ Rapor hatası."
        )
