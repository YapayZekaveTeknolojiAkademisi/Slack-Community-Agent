"""
Formatters — Özet sonuçlarını Slack Block Kit mesajlarına dönüştürür.

Desteklenen formatlar:
- Tek kanal özeti (brief/detailed)
- Çoklu kanal özeti (/channel-summary all)
- Kişisel ilgi alanları bölümü
- Hata ve boş durum mesajları
"""
from __future__ import annotations

from packages.slack.blocks.builder import MessageBuilder, BlockBuilder


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
    builder.add_text(summary_text)

    # Kişisel bölüm
    if personal_summary:
        builder.add_divider()
        builder.add_header("👤 Seni İlgilendiren Konular")
        builder.add_text(personal_summary)

    builder.add_divider()
    builder.add_context([
        f"🤖 Cemil tarafından oluşturuldu • Son {hours} saat • {mode_label}"
    ])

    return builder.build()


def format_multi_channel_blocks(
    channel_summaries: list[dict],
    hours: int,
    mode: str = "brief",
    personal_summary: str = "",
) -> list[dict]:
    """
    Çoklu kanal özeti (/channel-summary all).

    channel_summaries: [{"channel_id": "C...", "channel_name": "...", "summary": "...", "count": N}, ...]
    """
    builder = MessageBuilder()

    mode_label = "Kısa" if mode == "brief" else "Detaylı"
    active = len(channel_summaries)
    builder.add_header(f"📋 Tüm Kanallar — Son {hours} Saat ({mode_label})")
    builder.add_text(f"*{active} aktif kanal* özetlendi")
    builder.add_divider()

    for ch in channel_summaries:
        builder.add_text(
            f"*<#{ch['channel_id']}>*  •  {ch['count']} mesaj\n\n"
            f"{ch['summary']}"
        )
        builder.add_divider()

    # Kişisel bölüm
    if personal_summary:
        builder.add_header("👤 Seni İlgilendiren Konular")
        builder.add_text(personal_summary)
        builder.add_divider()

    builder.add_context([
        f"🤖 Cemil tarafından oluşturuldu • Son {hours} saat • {active} kanal"
    ])

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