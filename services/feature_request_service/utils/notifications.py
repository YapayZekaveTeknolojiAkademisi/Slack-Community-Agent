import logging
from enum import Enum, auto

logger = logging.getLogger("feature_request_service.notifications")

class NotificationType(Enum):
    ACTION_RESULT = auto()
    COMMAND_ERROR = auto()
    SYSTEM_REPORT = auto()
    SYSTEM_ALERT = auto()

EPHEMERAL_TYPES = {NotificationType.ACTION_RESULT, NotificationType.COMMAND_ERROR}

def send_notification(
    client,
    user_id: str,
    channel_id: str,
    notif_type: NotificationType,
    text: str,
    blocks: list = None,
):
    try:
        kwargs = {"channel": channel_id, "text": text}
        if blocks:
            kwargs["blocks"] = blocks

        if notif_type in EPHEMERAL_TYPES:
            kwargs["user"] = user_id
            client.chat_postEphemeral(**kwargs)
        else:
            client.chat_postMessage(**kwargs)
    except Exception as e:
        logger.error(f"Bildirim gönderilemedi (Tip: {notif_type}): {e}", exc_info=True)
