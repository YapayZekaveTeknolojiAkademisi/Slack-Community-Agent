"""Event Service — Slack bildirim yardimcilari."""
from __future__ import annotations

from packages.settings import get_settings
from packages.slack.client import slack_client
from packages.slack.blocks.builder import MessageBuilder, BlockBuilder
from packages.database.models.event import Event, LocationType
from ..utils.calendar import build_google_calendar_url
from ..logger import _logger


def _location_display(event: Event) -> str:
    """Lokasyon gosterimi: Slack kanali ise <#C123>, degilse tip adi."""
    loc = event.location_type
    if loc == LocationType.SLACK_CHANNEL and event.channel_id:
        return f"<#{event.channel_id}>"
    display = {
        LocationType.SLACK_CHANNEL: "Slack Kanali",
        LocationType.ZOOM: "Zoom",
        LocationType.YOUTUBE: "YouTube",
        LocationType.GOOGLE_MEET: "Google Meet",
        LocationType.DISCORD: "Discord",
        LocationType.OTHER: "Diger",
    }
    return display.get(loc, str(loc))


def _location_with_link_inline(event: Event) -> str:
    """
    Liste gosterimi icin lokasyon + inline link.
    Slack kanali: <#C123>
    Harici platform + link: "Zoom (<https://...|Link>)"
    Harici platform, link yok: "Zoom"
    """
    base = _location_display(event)
    if event.location_type != LocationType.SLACK_CHANNEL and event.link:
        return f"{base} (<{event.link}|Link>)"
    return base


def _calendar_location(event: Event) -> str:
    """Google Calendar icin mekan bilgisi: Slack kanaliysa kanal adi, degilse link."""
    if event.location_type == LocationType.SLACK_CHANNEL and event.channel_id:
        try:
            resp = slack_client.bot_client.conversations_info(channel=event.channel_id)
            if resp.get("ok"):
                return f"Slack — #{resp['channel']['name']}"
        except Exception:
            pass
        return f"Slack — {event.channel_id}"
    return event.link or ""


def _calendar_url(event: Event) -> str:
    return build_google_calendar_url(
        title=event.name,
        event_date=event.date,
        event_time=event.time,
        duration_minutes=event.duration_minutes,
        description=event.description,
        location=_calendar_location(event),
    )


def get_announcement_channels(event: Event) -> list[str]:
    """Duyuru kanallarini belirler: event_channel + (farkli ise) channel_id."""
    s = get_settings()
    channels = [s.event_channel]
    if (event.location_type == LocationType.SLACK_CHANNEL
            and event.channel_id
            and event.channel_id != s.event_channel):
        channels.append(event.channel_id)
    return channels


def post_announcement(event: Event, interest_count: int = 0) -> None:
    """Onay sonrasi ilk duyuru mesajini gonderir."""
    cal_url = _calendar_url(event)
    loc = _location_display(event)

    builder = MessageBuilder()
    builder.add_header("Yeni Etkinlik Duyurusu")

    lines = [
        f"*{event.name}*",
        "",
        f"*Konu:* {event.topic}",
        f"*Açıklama:* {event.description}",
        "",
        f"*Tarih:* {event.date.strftime('%d %B %Y')}",
        f"*Saat:* {event.time.strftime('%H:%M')}",
        f"*Süre:* {event.duration_minutes} dakika",
        f"*Lokasyon:* {loc}",
    ]
    if event.link:
        lines.append(f"*Link:* <{event.link}>")
    lines.append(f"*Düzenleyen:* <@{event.creator_slack_id}>")
    builder.add_text("\n".join(lines))

    builder.add_divider()
    builder.add_button("Katılacağım", "event_interest_btn", value=event.id, style="primary")
    builder.add_button("Google Takvime Ekle", "event_calendar_btn", value=event.id, url=cal_url)

    if interest_count > 0:
        builder.add_context([f"_{interest_count} kişi ilgi gösterdi_"])

    blocks = builder.build()
    text = f"Yeni Etkinlik: {event.name}"

    for ch in get_announcement_channels(event):
        try:
            slack_client.bot_client.chat_postMessage(channel=ch, text=text, blocks=blocks)
        except Exception as e:
            _logger.error("[EVT-NOTIFY] Duyuru gönderilemedi channel=%s: %s", ch, e)


def post_cancellation(event: Event, cancelled_by_slack_id: str) -> None:
    """Iptal duyurusu gonderir."""
    builder = MessageBuilder()
    builder.add_header("Etkinlik İptal Edildi")
    builder.add_text(
        f"*{event.name}*\n\n"
        f"*Tarih:* {event.date.strftime('%d %B %Y')} · *Saat:* {event.time.strftime('%H:%M')}\n"
        f"*Düzenleyen:* <@{event.creator_slack_id}>\n"
        f"*İptal Eden:* <@{cancelled_by_slack_id}>\n\n"
        "Bu etkinlik iptal edilmiştir."
    )

    blocks = builder.build()
    for ch in get_announcement_channels(event):
        try:
            slack_client.bot_client.chat_postMessage(
                channel=ch, text=f"Etkinlik İptal: {event.name}", blocks=blocks,
            )
        except Exception as e:
            _logger.error("[EVT-NOTIFY] İptal duyurusu gönderilemedi channel=%s: %s", ch, e)


def post_update_announcement(event: Event) -> None:
    """Guncelleme duyurusu gonderir."""
    cal_url = _calendar_url(event)
    loc = _location_display(event)

    builder = MessageBuilder()
    builder.add_header("Etkinlik Güncellendi")

    lines = [
        f"*{event.name}*",
        "",
        f"*Tarih:* {event.date.strftime('%d %B %Y')}",
        f"*Saat:* {event.time.strftime('%H:%M')}",
        f"*Süre:* {event.duration_minutes} dakika",
        f"*Lokasyon:* {loc}",
    ]
    if event.link:
        lines.append(f"*Link:* <{event.link}>")
    lines.append(f"*Düzenleyen:* <@{event.creator_slack_id}>")
    builder.add_text("\n".join(lines))

    builder.add_divider()
    builder.add_button("Katılacağım", "event_interest_btn", value=event.id, style="primary")
    builder.add_button("Google Takvime Ekle", "event_calendar_btn", value=event.id, url=cal_url)

    blocks = builder.build()
    for ch in get_announcement_channels(event):
        try:
            slack_client.bot_client.chat_postMessage(
                channel=ch, text=f"Etkinlik Güncellendi: {event.name}", blocks=blocks,
            )
        except Exception as e:
            _logger.error("[EVT-NOTIFY] Güncelleme duyurusu gönderilemedi channel=%s: %s", ch, e)


def send_dm(slack_id: str, text: str, blocks: list | None = None) -> None:
    """Kullaniciya DM gonderir."""
    try:
        slack_client.bot_client.chat_postMessage(channel=slack_id, text=text, blocks=blocks)
    except Exception as e:
        _logger.error("[EVT-NOTIFY] DM gönderilemedi user=%s: %s", slack_id, e)


def post_admin_request(event: Event) -> None:
    """Admin kanalina onay/red butonlu talep mesaji gonderir."""
    s = get_settings()
    loc = _location_display(event)

    builder = MessageBuilder()
    builder.add_header("Yeni Etkinlik Talebi")

    lines = [
        f"*{event.name}*",
        "",
        f"*Konu:* {event.topic}",
        f"*Açıklama:* {event.description}",
        "",
        f"*Tarih:* {event.date.strftime('%d %B %Y')}",
        f"*Saat:* {event.time.strftime('%H:%M')}",
        f"*Süre:* {event.duration_minutes} dakika",
        f"*Lokasyon:* {loc}",
    ]
    if event.link:
        lines.append(f"*Link:* <{event.link}>")
    lines.append(f"*Talep Eden:* <@{event.creator_slack_id}>")
    if event.yzta_request:
        lines.append(f"*YZTA'dan Beklenen:* {event.yzta_request}")
    builder.add_text("\n".join(lines))

    builder.add_divider()
    builder.add_button("Onayla", "event_approve_btn", value=event.id, style="primary")
    builder.add_button("Reddet", "event_reject_btn", value=event.id, style="danger")
    builder.add_context([f"_{event.id} · Gönderim: {event.created_at.strftime('%d %B %Y %H:%M')}_"])

    blocks = builder.build()
    try:
        slack_client.bot_client.chat_postMessage(
            channel=s.slack_admin_channel,
            text=f"Yeni Etkinlik Talebi: {event.name}",
            blocks=blocks,
        )
    except Exception as e:
        _logger.error("[EVT-NOTIFY] Admin talebi gönderilemedi: %s", e)
