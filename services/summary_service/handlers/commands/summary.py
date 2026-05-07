"""
/channel-summary slash command + buton action handler'ları.

Akış:
  1. /channel-summary        → mod seçim butonları göster (kısa/detaylı)
  2. /channel-summary all    → tüm kanallar için mod seçim butonları
  3. /channel-summary 12     → 12 saat parametresiyle mod seçim butonları
  4. /channel-summary help   → ephemeral komut özeti (challenge help benzeri)
  5. /summary, /summary help → aynı yardım (Slack app'te /summary tanımlı olmalı)
  6. Buton tıklama   → özet üretimini başlat
"""
from __future__ import annotations

import json

from slack_bolt import Ack, App

from packages.slack.blocks.builder import MessageBuilder

from packages.slack.client import slack_client
from packages.settings import get_settings
from ...core.message_fetcher import (
    fetch_channel_messages_detailed,
    get_user_channels,
    filter_personal_messages,
    slack_error_is_access_denied,
)
from ...core.chunker import chunk_messages
from ...core.summarizer import (
    is_summarizer_configured,
    summarizer_exc_is_transient_overload,
    summarize_chunks,
    summarize_personal,
    transient_overload_user_text,
)
from ...utils.formatters import (
    format_all_channels_empty_blocks,
    format_error_blocks,
    format_multi_channel_blocks,
    format_no_messages_blocks,
    format_summary_blocks,
    format_transient_overload_blocks,
    build_mode_selection_blocks,
    build_mode_selection_blocks_all,
)
from ...logger import _logger
from ...utils.notifications import (
    notify_summary_finished_admin,
    notify_summary_started_admin,
)

app: App = slack_client.app

_DEFAULT_HOURS = 24
_MIN_HOURS = 1
_MAX_HOURS = 168


def _humanize_fetch_error(code: str) -> str:
    """Tek kanal ephemeral için Slack hata kodunu Türkçe açıklamaya çevirir."""
    if code == "not_in_channel":
        return (
            "Mesajlar okunamadı: bot bu kanalın üyesi değil. Özeti görmek için botu kanala "
            "ekleyin veya genel bir kanalda komutu kullanın."
        )
    if code == "channel_not_found":
        return "Kanal bulunamadı veya artık erişilemiyor."
    if code == "missing_scope":
        return (
            "Slack uygulamasında mesaj geçmişi kapsamı eksik olabilir "
            "(ör. channels:history / groups:history)."
        )
    if code == "is_archived":
        return "Kanal arşivlenmiş; mesaj geçmişi okunamıyor."
    if code == "request_failed":
        return "Slack isteği başarısız (ağ veya sunucu). Lütfen biraz sonra tekrar deneyin."
    if code == "ratelimited":
        return transient_overload_user_text()
    return f"Mesajlar çekilemedi (Slack hatası: `{code}`)."


_BLOCK_GROQ_MISSING = (
    "Kanal özeti için Groq API anahtarı gerekli. Sunucuda `GROQ_API_KEY` ortam "
    "değişkenini tanımlayıp servisi yeniden başlatın."
)

_HELP_TRIGGERS = frozenset({"help", "yardım", "-h", "--help"})


def handle_summary_help(client, channel_id: str, user_id: str) -> None:
    """Challenge `handle_help` benzeri: komutların ephemeral blok özeti."""
    builder = MessageBuilder()
    builder.add_header("📖 Kanal özeti komutları")
    builder.add_text(
        "*`/channel-summary`*\n"
        "Bulunduğun kanal için son zaman diliminin özetini seç: *kısa* veya *detaylı* mod "
        "(butonlar; sonuç sana özel görünür).\n\n"
        f"*`/channel-summary <sayı>`* (1–{_MAX_HOURS} saat)\n"
        "Zaman aralığını değiştirip aynı mod seçim panelini gösterir. Örnek: `/channel-summary 48`.\n\n"
        "*`/channel-summary all`*\n"
        "Üye olduğun tüm kanallar için rollup özet; yine mod seçilir. "
        "Çok kanal daha uzun sürebilir ve thread başına daha sıkı limitler kullanılır.\n\n"
        "*`/channel-summary help`*\n"
        "(veya `/channel-summary yardım`) Bu yardımı gösterir.\n\n"
        "*`/summary`* veya *`/summary help`*\n"
        "Slack uygulamasında `/summary` kısayolu tanımlandıysa aynı yardımı açar. "
        "Özet almak için asıl komut **`/channel-summary`**."
    )
    builder.add_divider()
    builder.add_header("İpuçları")
    builder.add_text(
        "• Botun özeti çıkarmak için kanal üyesi olması ve uygun Slack kapsamları gereklidir.\n"
        "• Mention aldığın mesajlar ve thread yanıtların özette *Seni ilgilendiren konular* bölümünde özetlenebilir.\n"
        "• Yoğunluk veya kısa süreli kota mesajında birkaç dakika sonra yeniden denemek yararlıdır.\n"
    )
    builder.add_context(
        ["Bilinmeyen parametre yazarsanız `/channel-summary help` ile seçeneklere bakın."]
    )

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="📖 Kanal özeti — yardım",
        blocks=builder.build(),
    )


# ═══════════════════════════════════════════════════════════════════
# SLASH COMMAND
# ═══════════════════════════════════════════════════════════════════

@app.command("/channel-summary")
def handle_summary_command(ack: Ack, body: dict, client):
    """
    /channel-summary       → bu kanalın mod seçim butonlarını göster
    /channel-summary all   → tüm kanallar mod seçim butonları
    /channel-summary 12    → 12 saat parametresiyle mod seçim butonları
    /channel-summary help  → komutların ephemeral özeti
    """
    ack()

    user_id = body.get("user_id", "")
    channel_id = body.get("channel_id", "")
    text = body.get("text", "").strip()
    parts = text.split()

    first = parts[0].lower() if parts else ""
    if first in _HELP_TRIGGERS:
        handle_summary_help(client, channel_id, user_id)
        return

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
    if parts:
        try:
            hours = int(parts[0])
            hours = max(_MIN_HOURS, min(_MAX_HOURS, hours))
        except ValueError:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=(
                    f"⚠️ Geçersiz parametre: `{text}`\n"
                    f"Bakınız `/channel-summary help` — kullanım: `/channel-summary`, "
                    "`/channel-summary all` veya `/channel-summary 12`"
                ),
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


@app.command("/summary")
def handle_summary_short_help(ack: Ack, body: dict, client):
    """
    Workspace'te Slack uygulamasına `/summary` slash komutu eklendiğinde yardımı gösterir.
    Özet oluşturmak için `/channel-summary` kullanın.
    """
    ack()

    user_id = body.get("user_id", "")
    channel_id = body.get("channel_id", "")
    parts = body.get("text", "").strip().split()

    first = parts[0].lower() if parts else ""
    if parts and first not in _HELP_TRIGGERS:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=(
                "`/summary` burada yalnızca yardım içindir. "
                "Özet için `/channel-summary` kullanın (`/channel-summary help` liste verir)."
            ),
        )
        return

    handle_summary_help(client, channel_id, user_id)


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

    if not is_summarizer_configured():
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="",
            blocks=format_error_blocks(_BLOCK_GROQ_MISSING),
        )
        return

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"⏳ Son {hours} saatin {'kısa' if mode == 'brief' else 'detaylı'} özeti hazırlanıyor...",
    )

    notify_summary_started_admin(
        scope="single",
        user_id=user_id,
        invoke_channel_id=channel_id,
        hours=hours,
        mode=mode,
        target_channel_id=channel_id,
    )

    # Mesajları çek
    outcome = fetch_channel_messages_detailed(channel_id=channel_id, hours=hours)
    if outcome.slack_error:
        _logger.warning(
            "[Summary] Fetch failed ch=%s code=%s",
            channel_id,
            outcome.slack_error,
        )
        if outcome.slack_error == "ratelimited":
            blocks_err = format_transient_overload_blocks(transient_overload_user_text())
        else:
            blocks_err = format_error_blocks(_humanize_fetch_error(outcome.slack_error))
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="",
            blocks=blocks_err,
        )
        notify_summary_finished_admin(
            scope="single",
            user_id=user_id,
            invoke_channel_id=channel_id,
            hours=hours,
            mode=mode,
            status="fail",
            detail=f"rsn=fetch code={outcome.slack_error}",
        )
        return

    messages = outcome.messages

    if not messages:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text=f"Son {hours} saatte mesaj bulunamadı.",
            blocks=format_no_messages_blocks(channel_id, hours),
        )
        notify_summary_finished_admin(
            scope="single",
            user_id=user_id,
            invoke_channel_id=channel_id,
            hours=hours,
            mode=mode,
            status="empty",
            detail="rsn=no_messages tgt_ch=" + channel_id,
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
        if summarizer_exc_is_transient_overload(exc):
            blocks_err = format_transient_overload_blocks(transient_overload_user_text())
        else:
            blocks_err = format_error_blocks("Özet oluşturulurken hata oluştu.")
        client.chat_postEphemeral(
            channel=channel_id, user=user_id, text="",
            blocks=blocks_err,
        )
        notify_summary_finished_admin(
            scope="single",
            user_id=user_id,
            invoke_channel_id=channel_id,
            hours=hours,
            mode=mode,
            status="fail",
            detail=(
                "rsn=groq_transient_overload"
                if summarizer_exc_is_transient_overload(exc)
                else "rsn=groq_summarize_error"
            ),
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
    notify_summary_finished_admin(
        scope="single",
        user_id=user_id,
        invoke_channel_id=channel_id,
        hours=hours,
        mode=mode,
        status="ok",
        detail=f"msgs={len(messages)} tgt_ch={channel_id}",
    )


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

    if not is_summarizer_configured():
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="",
            blocks=format_error_blocks(_BLOCK_GROQ_MISSING),
        )
        return

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"⏳ Tüm kanalların son {hours} saatlik {'kısa' if mode == 'brief' else 'detaylı'} özeti hazırlanıyor... Bu biraz zaman alabilir.",
    )

    notify_summary_started_admin(
        scope="all",
        user_id=user_id,
        invoke_channel_id=channel_id,
        hours=hours,
        mode=mode,
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
        notify_summary_finished_admin(
            scope="all",
            user_id=user_id,
            invoke_channel_id=channel_id,
            hours=hours,
            mode=mode,
            status="fail",
            detail="rsn=channel_list_error",
        )
        return

    if not user_channels:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="Üye olduğun hiçbir kanal bulunamadı.",
        )
        notify_summary_finished_admin(
            scope="all",
            user_id=user_id,
            invoke_channel_id=channel_id,
            hours=hours,
            mode=mode,
            status="empty",
            detail="rsn=no_member_channels",
        )
        return

    st = get_settings()

    # Her kanalı özetle
    channel_summaries: list[dict] = []
    all_personal_msgs: list = []
    skipped_access = 0
    skipped_other = 0
    slack_rate_limited = 0
    groq_overload_channels = 0

    for ch in user_channels:
        outcome = fetch_channel_messages_detailed(
            channel_id=ch.id,
            hours=hours,
            max_messages=200,
            max_threads=st.summary_max_threads_all,
            max_replies_per_thread=st.summary_max_replies_per_thread_all,
        )
        if outcome.slack_error:
            if outcome.slack_error == "ratelimited":
                slack_rate_limited += 1
            elif slack_error_is_access_denied(outcome.slack_error):
                skipped_access += 1
            else:
                skipped_other += 1
            _logger.warning(
                "[Summary All] Skip ch=%s name=%s code=%s",
                ch.id,
                ch.name,
                outcome.slack_error,
            )
            continue

        msgs = outcome.messages
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
            if summarizer_exc_is_transient_overload(exc):
                groq_overload_channels += 1
                _logger.warning("[Summary All] Groq/overload skip ch=%s: %s", ch.name, exc)
            else:
                skipped_other += 1
                _logger.warning("[Summary All] Skipping channel %s — summarize failed: %s", ch.name, exc)
            continue

    preamble_lines: list[str] = []
    if slack_rate_limited:
        preamble_lines.append(
            f"⚠️ *{slack_rate_limited} kanal* Slack hız limiti nedeniyle atlandı — yoğunluk geçince tekrar deneyin."
        )
    if groq_overload_channels:
        preamble_lines.append(
            f"⚠️ *{groq_overload_channels} kanal* özet kotası veya zaman aşımı nedeniyle atlandı."
        )
    if skipped_access:
        preamble_lines.append(
            f"⚠️ *{skipped_access} kanal* için mesaj çekilemedi "
            "(bot o kanallarda üye değil veya erişim/izin yok)."
        )
    if skipped_other:
        preamble_lines.append(
            f"⚠️ *{skipped_other} kanal* özet veya API hatası nedeniyle atlandı."
        )

    if not channel_summaries:
        hit_transient = slack_rate_limited > 0 or groq_overload_channels > 0
        if hit_transient:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Yoğunluk — lütfen birkaç dakika sonra tekrar deneyin.",
                blocks=format_transient_overload_blocks(transient_overload_user_text()),
            )
            notify_summary_finished_admin(
                scope="all",
                user_id=user_id,
                invoke_channel_id=channel_id,
                hours=hours,
                mode=mode,
                status="fail",
                detail=(
                    f"rsn=transient_load slack_r={slack_rate_limited} groq_ov={groq_overload_channels}"
                ),
            )
            return
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Özet oluşturulamadı veya uygun içerik yok."
            if (skipped_access or skipped_other)
            else f"Son {hours} saatte özetlenecek mesaj bulunamadı.",
            blocks=format_all_channels_empty_blocks(hours, preamble_lines or None),
        )
        notify_summary_finished_admin(
            scope="all",
            user_id=user_id,
            invoke_channel_id=channel_id,
            hours=hours,
            mode=mode,
            status="empty",
            detail=(
                f"rsn=no_summaries skip_acc={skipped_access} skip_ot={skipped_other} "
                f"slack_r={slack_rate_limited} groq_ov={groq_overload_channels}"
            ),
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
        preamble_lines=preamble_lines or None,
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
    notify_summary_finished_admin(
        scope="all",
        user_id=user_id,
        invoke_channel_id=channel_id,
        hours=hours,
        mode=mode,
        status="ok",
        detail=(
            f"ch_ok={len(channel_summaries)} skip_acc={skipped_access} skip_ot={skipped_other} "
            f"slack_r={slack_rate_limited} groq_ov={groq_overload_channels}"
        ),
    )


@app.action("summary_all_brief")
def handle_summary_all_brief(ack, body, client):
    ack()
    _handle_all_channels(body, client, mode="brief")


@app.action("summary_all_detailed")
def handle_summary_all_detailed(ack, body, client):
    ack()
    _handle_all_channels(body, client, mode="detailed")