"""
/channel-summary slash command + buton action handler'ları.

Akış:
  1. /channel-summary        → mod seçim butonları göster (kısa/detaylı)
  2. /channel-summary all    → tüm kanallar için mod seçim butonları
  3. /channel-summary 12     → 12 saat parametresiyle mod seçim butonları
  4. Buton tıklama   → özet üretimini başlat
"""
from __future__ import annotations

import json

from slack_bolt import Ack, App

from packages.slack.client import slack_client
from ...core.message_fetcher import (
    fetch_channel_messages,
    get_user_channels,
    filter_personal_messages,
)
from ...core.chunker import chunk_messages
from ...core.summarizer import summarize_chunks, summarize_personal
from ...utils.formatters import (
    format_summary_blocks,
    format_multi_channel_blocks,
    format_no_messages_blocks,
    format_error_blocks,
    build_mode_selection_blocks,
    build_mode_selection_blocks_all,
)
from ...logger import _logger

app: App = slack_client.app

_DEFAULT_HOURS = 24
_MIN_HOURS = 1
_MAX_HOURS = 168


# ═══════════════════════════════════════════════════════════════════
# SLASH COMMAND
# ═══════════════════════════════════════════════════════════════════

@app.command("/channel-summary")
def handle_summary_command(ack: Ack, body: dict, client):
    """
    /channel-summary       → bu kanalın mod seçim butonlarını göster
    /channel-summary all   → tüm kanallar mod seçim butonları
    /channel-summary 12    → 12 saat parametresiyle mod seçim butonları
    """
    ack()

    user_id = body.get("user_id", "")
    channel_id = body.get("channel_id", "")
    text = body.get("text", "").strip()

    # /channel-summary all
    if text.lower() == "all":
        meta = json.dumps({"channel_id": channel_id, "hours": _DEFAULT_HOURS, "user_id": user_id})
        blocks = build_mode_selection_blocks_all()
        for block in blocks:
            if block.get("type") == "actions":
                for element in block.get("elements", []):
                    element["value"] = meta

        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Tüm kanallar özeti — mod seçin",
            blocks=blocks,
        )
        return

    # Saat parametresi parse
    hours = _DEFAULT_HOURS
    if text:
        try:
            hours = int(text)
            hours = max(_MIN_HOURS, min(_MAX_HOURS, hours))
        except ValueError:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"⚠️ Geçersiz parametre: `{text}`\n"
                     f"Kullanım: `/channel-summary`, `/channel-summary all` veya `/channel-summary 12`",
            )
            return

    # Tek kanal — mod seçim butonları
    meta = json.dumps({"channel_id": channel_id, "hours": hours, "user_id": user_id})
    blocks = build_mode_selection_blocks()
    for block in blocks:
        if block.get("type") == "actions":
            for element in block.get("elements", []):
                element["value"] = meta

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="Kanal özeti — mod seçin",
        blocks=blocks,
    )


# ═══════════════════════════════════════════════════════════════════
# BUTON HANDLER'LARI — Tek Kanal
# ═══════════════════════════════════════════════════════════════════

def _handle_single_channel(body: dict, client, mode: str):
    """Tek kanal özet üretimini çalıştırır."""
    action = body["actions"][0]
    meta = json.loads(action["value"])
    channel_id = meta["channel_id"]
    hours = meta["hours"]
    user_id = meta["user_id"]

    _logger.info(
        "[Summary] Single channel — user=%s channel=%s hours=%d mode=%s",
        user_id, channel_id, hours, mode,
    )

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"⏳ Son {hours} saatin {'kısa' if mode == 'brief' else 'detaylı'} özeti hazırlanıyor...",
    )

    # Mesajları çek
    try:
        messages = fetch_channel_messages(channel_id=channel_id, hours=hours)
    except Exception as exc:
        _logger.error("[Summary] Fetch failed: %s", exc, exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id, user=user_id, text="",
            blocks=format_error_blocks("Mesajlar çekilemedi. Cemil'in kanala üye olduğundan emin olun."),
        )
        return

    if not messages:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text=f"Son {hours} saatte mesaj bulunamadı.",
            blocks=format_no_messages_blocks(channel_id, hours),
        )
        return

    # Kişisel mesajları filtrele
    personal_msgs = filter_personal_messages(messages, user_id)

    # Ana özet
    try:
        chunks = chunk_messages(messages)
        summary = summarize_chunks(chunks, mode=mode)
    except Exception as exc:
        _logger.error("[Summary] Summarization failed: %s", exc, exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id, user=user_id, text="",
            blocks=format_error_blocks("Özet oluşturulurken hata oluştu."),
        )
        return

    # Kişisel özet
    personal_summary = ""
    if personal_msgs:
        try:
            personal_chunks = chunk_messages(personal_msgs)
            personal_summary = summarize_personal(personal_chunks)
        except Exception as exc:
            _logger.warning("[Summary] Personal summary failed: %s", exc)

    # Sonucu gönder
    blocks = format_summary_blocks(
        summary_text=summary,
        channel_id=channel_id,
        hours=hours,
        message_count=len(messages),
        mode=mode,
        personal_summary=personal_summary,
    )
    client.chat_postEphemeral(
        channel=channel_id, user=user_id,
        text=f"📋 Son {hours} saatlik kanal özeti",
        blocks=blocks,
    )
    _logger.info("[Summary] Delivered to user %s — %d messages, mode=%s", user_id, len(messages), mode)


@app.action("summary_brief")
def handle_summary_brief(ack, body, client):
    ack()
    _handle_single_channel(body, client, mode="brief")


@app.action("summary_detailed")
def handle_summary_detailed(ack, body, client):
    ack()
    _handle_single_channel(body, client, mode="detailed")


# ═══════════════════════════════════════════════════════════════════
# BUTON HANDLER'LARI — Tüm Kanallar
# ═══════════════════════════════════════════════════════════════════

def _handle_all_channels(body: dict, client, mode: str):
    """Kullanıcının üye olduğu tüm kanalları özetler."""
    action = body["actions"][0]
    meta = json.loads(action["value"])
    channel_id = meta["channel_id"]
    hours = meta["hours"]
    user_id = meta["user_id"]

    _logger.info(
        "[Summary All] user=%s hours=%d mode=%s",
        user_id, hours, mode,
    )

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"⏳ Tüm kanalların son {hours} saatlik {'kısa' if mode == 'brief' else 'detaylı'} özeti hazırlanıyor... Bu biraz zaman alabilir.",
    )

    # Kullanıcının kanallarını al
    try:
        user_channels = get_user_channels(user_id)
    except Exception as exc:
        _logger.error("[Summary All] Channel list failed: %s", exc, exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id, user=user_id, text="",
            blocks=format_error_blocks("Kanal listesi alınamadı."),
        )
        return

    if not user_channels:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="Üye olduğun hiçbir kanal bulunamadı.",
        )
        return

    # Her kanalı özetle
    channel_summaries: list[dict] = []
    all_personal_msgs: list = []

    for ch in user_channels:
        try:
            msgs = fetch_channel_messages(channel_id=ch.id, hours=hours, max_messages=200)
        except Exception:
            _logger.warning("[Summary All] Skipping channel %s — fetch failed", ch.name)
            continue

        if not msgs:
            continue

        # Kişisel mesajları topla
        personal = filter_personal_messages(msgs, user_id)
        all_personal_msgs.extend(personal)

        try:
            chunks = chunk_messages(msgs)
            summary = summarize_chunks(chunks, mode=mode)
            channel_summaries.append({
                "channel_id": ch.id,
                "channel_name": ch.name,
                "summary": summary,
                "count": len(msgs),
            })
        except Exception as exc:
            _logger.warning("[Summary All] Skipping channel %s — summarize failed: %s", ch.name, exc)
            continue

    if not channel_summaries:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text=f"Son {hours} saatte hiçbir kanalda özetlenecek mesaj bulunamadı.",
        )
        return

    # Kişisel özet
    personal_summary = ""
    if all_personal_msgs:
        try:
            personal_chunks = chunk_messages(all_personal_msgs)
            personal_summary = summarize_personal(personal_chunks)
        except Exception as exc:
            _logger.warning("[Summary All] Personal summary failed: %s", exc)

    # Sonucu gönder
    blocks = format_multi_channel_blocks(
        channel_summaries=channel_summaries,
        hours=hours,
        mode=mode,
        personal_summary=personal_summary,
    )
    client.chat_postEphemeral(
        channel=channel_id, user=user_id,
        text=f"📋 Tüm kanallar — son {hours} saatlik özet",
        blocks=blocks,
    )
    _logger.info(
        "[Summary All] Delivered to user %s — %d channels, mode=%s",
        user_id, len(channel_summaries), mode,
    )


@app.action("summary_all_brief")
def handle_summary_all_brief(ack, body, client):
    ack()
    _handle_all_channels(body, client, mode="brief")


@app.action("summary_all_detailed")
def handle_summary_all_detailed(ack, body, client):
    ack()
    _handle_all_channels(body, client, mode="detailed")