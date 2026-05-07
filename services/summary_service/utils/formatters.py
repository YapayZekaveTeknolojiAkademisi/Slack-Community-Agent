"""
Formatters — Özet sonuçlarını Slack Block Kit mesajlarına dönüştürür.

Desteklenen formatlar:
- Tek kanal özeti (brief/detailed)
- Çoklu kanal özeti (/channel-summary all)
- Kişisel ilgi alanları bölümü
- Hata ve boş durum mesajları

Slack sınırları: blok başına mrkdwn/plain_text ~3000 karakter; mesajda en fazla ~50 blok.
"""
from __future__ import annotations

from packages.settings import get_settings
from packages.slack.blocks.builder import MessageBuilder, BlockBuilder

# Ephemeral çoklu kanal: blok sayısı + tek blok başına metin
_MAX_CHANNELS_IN_EPHEMERAL = 14
_PER_CHANNEL_SUMMARY_CHARS = 2999
_MAX_SINGLE_SUMMARY_CHARS = 2999 * 12  # tek mesajda makul üst sınır (~12 plain section)


def _summary_footer_attribution(extra_segments: list[str]) -> str:
    """Footer: oluşturan etiketi + env'den özelleştirilir (`SUMMARY_ATTRIBUTION_LABEL`)."""
    raw = get_settings().summary_attribution_label
    label = (raw or "").strip() or "Özet asistanı"
    base = f"🤖 {label} tarafından oluşturuldu"
    tail = [base, *extra_segments]
    return " • ".join(tail)


def format_summary_blocks(
    summary_text: str,
    channel_id: str,
    hours: int,
    message_count: int,
    mode: str = "detailed",
    personal_summary: str = "",
) -> list[dict]:
    """Tek kanal özeti — brief veya detailed."""
    builder = MessageBuilder()

    mode_label = "Kısa Özet" if mode == "brief" else "Detaylı Özet"
    builder.add_header(f"📋 Son {hours} Saatlik {mode_label}")
    builder.add_text(f"Kanal: <#{channel_id}> • {message_count} mesaj işlendi")
    builder.add_divider()
    body = summary_text or ""
    if len(body) > _MAX_SINGLE_SUMMARY_CHARS:
        body = body[: _MAX_SINGLE_SUMMARY_CHARS - 1] + "…"
    builder.add_plain_text(body)

    # Kişisel bölüm
    if personal_summary:
        builder.add_divider()
        builder.add_header("👤 Seni İlgilendiren Konular")
        ps = personal_summary
        if len(ps) > _MAX_SINGLE_SUMMARY_CHARS:
            ps = ps[: _MAX_SINGLE_SUMMARY_CHARS - 1] + "…"
        builder.add_plain_text(ps)

    builder.add_divider()
    builder.add_context([
        _summary_footer_attribution([f"Son {hours} saat", mode_label]),
    ])

    return builder.build()


def format_multi_channel_blocks(
    channel_summaries: list[dict],
    hours: int,
    mode: str = "brief",
    personal_summary: str = "",
    preamble_lines: list[str] | None = None,
) -> list[dict]:
    """
    Çoklu kanal özeti (/channel-summary all).

    channel_summaries: [{"channel_id": "C...", "channel_name": "...", "summary": "...", "count": N}, ...]
    preamble_lines: Opsiyonel uyarı satırları (ör. atlanan kanal sayısı)
    """
    builder = MessageBuilder()

    mode_label = "Kısa" if mode == "brief" else "Detaylı"
    total_active = len(channel_summaries)
    omitted = max(0, total_active - _MAX_CHANNELS_IN_EPHEMERAL)
    if omitted:
        channel_summaries = channel_summaries[:_MAX_CHANNELS_IN_EPHEMERAL]

    builder.add_header(f"📋 Tüm Kanallar — Son {hours} Saat ({mode_label})")
    if preamble_lines:
        for pl in preamble_lines:
            builder.add_text(pl)
        builder.add_divider()

    if omitted:
        builder.add_text(
            f"*{total_active} kanal* özetlendi — Slack blok limiti nedeniyle ilk "
            f"*{len(channel_summaries)}* kanal gösteriliyor."
        )
    else:
        builder.add_text(f"*{total_active} aktif kanal* özetlendi")
    builder.add_divider()

    for ch in channel_summaries:
        builder.add_text(f"*<#{ch['channel_id']}>*  •  {ch['count']} mesaj")
        body = ch.get("summary") or ""
        if len(body) > _PER_CHANNEL_SUMMARY_CHARS:
            body = body[: _PER_CHANNEL_SUMMARY_CHARS - 1] + "…"
        builder.add_plain_text(body)
        builder.add_divider()

    # Kişisel bölüm
    if personal_summary:
        builder.add_header("👤 Seni İlgilendiren Konular")
        ps = personal_summary
        if len(ps) > _PER_CHANNEL_SUMMARY_CHARS:
            ps = ps[: _PER_CHANNEL_SUMMARY_CHARS - 1] + "…"
        builder.add_plain_text(ps)
        builder.add_divider()

    builder.add_context([
        _summary_footer_attribution([f"Son {hours} saat", f"{total_active} kanal"]),
    ])

    return builder.build()


def format_all_channels_empty_blocks(
    hours: int,
    preamble_lines: list[str] | None = None,
) -> list[dict]:
    """Tüm kanallar modunda hiç özet üretilemediğinde (veya sadece uyarı göstermek için)."""
    builder = MessageBuilder()
    builder.add_header("📋 Tüm Kanallar Özeti")
    builder.add_text(
        f"Son *{hours} saat* için özet oluşturulacak mesaj bulunan kanal yok."
    )
    if preamble_lines:
        builder.add_divider()
        for line in preamble_lines:
            builder.add_text(line)
    return builder.build()


def format_no_messages_blocks(channel_id: str, hours: int) -> list[dict]:
    builder = MessageBuilder()
    builder.add_header(f"📋 Son {hours} Saatlik Kanal Özeti")
    builder.add_text(
        f"<#{channel_id}> kanalında son {hours} saat içinde özetlenecek mesaj bulunamadı."
    )
    return builder.build()


def format_error_blocks(error_msg: str) -> list[dict]:
    builder = MessageBuilder()
    builder.add_header("⚠️ Özet Oluşturulamadı")
    builder.add_text(f"Bir hata oluştu: {error_msg}")
    builder.add_context([
        "Lütfen tekrar deneyin. Sorun devam ederse yöneticiye bildirin."
    ])
    return builder.build()


def format_transient_overload_blocks(body: str) -> list[dict]:
    """Slack/Groq hız limiti veya geçici kapasite — 'sistem çöktü' algısı yok."""
    builder = MessageBuilder()
    builder.add_header("⏳ Şu an yoğun")
    builder.add_text(body)
    builder.add_context([
        "Servis ayakta; bu geçici bir sınırlama. Lütfen birkaç dakika sonra tekrar deneyin.",
    ])
    return builder.build()


def build_mode_selection_blocks() -> list[dict]:
    """
    /channel-summary yazıldığında gösterilecek mod seçim butonları.
    Kullanıcı brief veya detailed seçer.
    """
    builder = MessageBuilder()
    builder.add_header("📋 Kanal Özeti")
    builder.add_text("Nasıl bir özet istersin?")

    blocks = builder.build()

    # Butonlar
    blocks.append(BlockBuilder.actions(
        elements=[
            BlockBuilder.button(
                text="⚡ Kısa Özet",
                action_id="summary_brief",
                style="primary",
                value="brief",
            ),
            BlockBuilder.button(
                text="📖 Detaylı Özet",
                action_id="summary_detailed",
                value="detailed",
            ),
        ],
        block_id="summary_mode_select",
    ))

    return blocks


def build_mode_selection_blocks_all() -> list[dict]:
    """
    /channel-summary all yazıldığında gösterilecek mod seçim butonları.
    """
    builder = MessageBuilder()
    builder.add_header("📋 Tüm Kanallar Özeti")
    builder.add_text("Tüm kanallar için nasıl bir özet istersin?")

    blocks = builder.build()

    blocks.append(BlockBuilder.actions(
        elements=[
            BlockBuilder.button(
                text="⚡ Kısa Özet",
                action_id="summary_all_brief",
                style="primary",
                value="brief",
            ),
            BlockBuilder.button(
                text="📖 Detaylı Özet",
                action_id="summary_all_detailed",
                value="detailed",
            ),
        ],
        block_id="summary_all_mode_select",
    ))

    return blocks