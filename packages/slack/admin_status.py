"""Admin kanalı (`SLACK_ADMIN_CHANNEL`) durum mesajları — okunaklı Türkçe blok formatı."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from packages.settings import get_settings
from packages.slack.client import slack_client

# Challenge / event admin bloklari ile ayni gorsel ayirici (Slack monospace'te tek satir)
ADMIN_STATUS_DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


def _compose_admin_text(headline: str, detail_lines: Sequence[str] | None) -> str:
    h = (headline or "").strip()
    title = f"*{h}*" if h else "*Servis durumu*"
    parts = [f"{ADMIN_STATUS_DIVIDER}\n{title}\n{ADMIN_STATUS_DIVIDER}"]
    if detail_lines:
        bullets = [f"• {(ln or '').strip()}" for ln in detail_lines if (ln or "").strip()]
        if bullets:
            parts.append("\n".join(bullets))
    return "\n".join(parts)


def post_admin_status(
    headline: str,
    *,
    detail_lines: Sequence[str] | None = None,
    log: Any | None = None,
) -> None:
    """
    İngilizce / özet / özellik talebi servislerinin başlangıç ve kapanış bildirimleri için
    admin kanalına tek bir okunaklı blok gönderir (challenge ve event servisindeki çizgi düzeniyle uyumlu).
    """
    ch = (get_settings().slack_admin_channel or "").strip()
    if not ch:
        warn = logging.getLogger(__name__).warning
        warn("[ADMIN-STATUS] SLACK_ADMIN_CHANNEL bos; admin post atlandi: %s", headline[:80])
        return

    text = _compose_admin_text(headline, detail_lines)
    try:
        slack_client.bot_client.chat_postMessage(channel=ch, text=text)
    except Exception as exc:  # slack sdk / ag
        if log is not None and callable(getattr(log, "warning", None)):
            log.warning("[ADMIN-STATUS] admin post failed: %s headline=%s", exc, headline[:80])
        else:
            logging.getLogger(__name__).warning(
                "[ADMIN-STATUS] admin post failed: %s headline=%s", exc, headline[:80]
            )
