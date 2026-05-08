"""Event Service — Slack bildirim yardimcilari."""
from __future__ import annotations

from packages.settings import get_settings
from packages.slack.admin_status import ADMIN_STATUS_DIVIDER
from packages.slack.client import slack_client
from packages.slack.blocks.builder import MessageBuilder
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
    """Duyuru kanalları: SLACK_ANNOUNCEMENT_CHANNEL doluysa yalnızca o kanal; değilse eski davranış."""
    s = get_settings()
    ann = (s.slack_announcement_channel or "").strip()
    if ann:
        return [ann]
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

    targets = get_announcement_channels(event)
    for ch in targets:
        try:
            slack_client.bot_client.chat_postMessage(channel=ch, text=text, blocks=blocks)
            _logger.info(
                "[EVT-NOTIFY] Onay duyurusu gönderildi event=%s channel=%s",
                event.id,
                ch,
            )
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
    """Kullanıcıya DM gönderir (önce conversations_open — user ID ile doğrudan post güvenilir değil)."""
    try:
        resp = slack_client.bot_client.conversations_open(users=slack_id)
        if not resp.get("ok"):
            _logger.error(
                "[EVT-NOTIFY] DM açılamadı user=%s err=%s",
                slack_id,
                resp.get("error"),
            )
            return
        ch = resp["channel"]["id"]
        kw: dict = {"channel": ch, "text": text or " "}
        if blocks:
            kw["blocks"] = blocks
        slack_client.bot_client.chat_postMessage(**kw)
    except Exception as e:
        _logger.error("[EVT-NOTIFY] DM gönderilemedi user=%s: %s", slack_id, e)


def post_admin_request(event: Event) -> tuple[str, str] | None:
    """Admin kanalına onay/red butonlu talep gönderir. Başarıda ``(kanal_id, ts)`` döner (mesaj güncellemesi için)."""
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
        resp = slack_client.bot_client.chat_postMessage(
            channel=s.slack_admin_channel,
            text=f"Yeni Etkinlik Talebi: {event.name}",
            blocks=blocks,
        )
        ts = resp.get("ts")
        if not ts:
            msg = resp.get("message")
            if isinstance(msg, dict):
                ts = msg.get("ts")
        if not ts:
            _logger.warning("[EVT-NOTIFY] Admin talebinde ts yok event=%s resp_ok=%s", event.id, resp.get("ok"))
            return None
        return (s.slack_admin_channel, ts)
    except Exception as e:
        _logger.error("[EVT-NOTIFY] Admin talebi gönderilemedi: %s", e)
        return None


def update_admin_request_message(
    event: Event,
    *,
    outcome: str,
    admin_id: str | None,
    note: str | None,
) -> None:
    """
    Admin kanalındaki talep mesajını günceller: Onayla/Reddet butonları kaldırılır,
    yalnızca karar özeti ve etkinlik bilgisi kalır (aynı mesaj satırında chat.update).
    ``outcome``: approved | rejected | timeout
    """
    meta = dict(event.meta or {})
    ch = meta.get("admin_slack_channel")
    ts = meta.get("admin_slack_ts")
    if not ch or not ts:
        _logger.warning(
            "[EVT-NOTIFY] Admin mesajı güncellenemedi (meta eksik: kanal/ts). "
            "Eski taleplerde olabilir veya kayıt yazılamadı. event=%s",
            event.id,
        )
        return

    loc = _location_display(event)
    note = (note or "").strip()

    if outcome == "approved":
        builder = MessageBuilder()
        builder.add_header("Etkinlik talebi — onaylandı")
        decision = (
            f"<@{admin_id}> bu talebi *onayladı*."
            if admin_id
            else "Bu talep *onaylandı*."
        )
    elif outcome == "rejected":
        builder = MessageBuilder()
        builder.add_header("Etkinlik talebi — reddedildi")
        decision = (
            f"<@{admin_id}> bu talebi *reddetti*."
            if admin_id
            else "Bu talep *reddedildi*."
        )
    else:
        builder = MessageBuilder()
        builder.add_header("Etkinlik talebi — zaman aşımı")
        decision = "Bu talep *zaman aşımı* nedeniyle otomatik olarak reddedildi."

    detail_lines = [
        decision,
        "",
        f"*{event.name}*",
        "",
        f"*Konu:* {event.topic}",
        f"*Tarih:* {event.date.strftime('%d %B %Y')} · *Saat:* {event.time.strftime('%H:%M')}",
        f"*Lokasyon:* {loc}",
        f"*Talep eden:* <@{event.creator_slack_id}>",
    ]
    if note:
        detail_lines.extend(["", f"*Yönetici notu / gerekçe:*\n{note}"])

    builder.add_text("\n".join(detail_lines))
    builder.add_context(
        [f"_Bu mesaj yalnızca admin kanalı içindir · Butonlar kapatıldı · `{event.id}`_"]
    )

    blocks = builder.build()
    fallback = f"Etkinlik talebi ({event.name}): {outcome}"
    try:
        upd = slack_client.bot_client.chat_update(
            channel=ch,
            ts=ts,
            text=fallback,
            blocks=blocks,
        )
        if not upd.get("ok"):
            _logger.error(
                "[EVT-NOTIFY] Admin talebi chat_update ok=false event=%s err=%s",
                event.id,
                upd.get("error"),
            )
        else:
            _logger.info("[EVT-NOTIFY] Admin talep mesajı güncellendi event=%s ts=%s", event.id, ts)
    except Exception as e:
        _logger.error("[EVT-NOTIFY] Admin talebi güncellenemedi event=%s: %s", event.id, e)


def notify_event_service_startup(*, socket_bound: bool) -> None:
    """
    Event servisi ayakta — admin kanalına okunaklı başlangıç özeti.
    compose'ta çoğunlukla socket_bound=False (scheduler-only).
    """
    s = get_settings()
    admin_channel = (s.slack_admin_channel or "").strip()
    if not admin_channel:
        _logger.warning("[NOTIFY] SLACK_ADMIN_CHANNEL bos; event startup admin post atlaniyor")
        return

    if socket_bound:
        socket_line = (
            "• *Socket Mode* bu süreçte *açık*; Slack üzerinden bağlı ve istek dinleniyor.\n"
            "• Slash komutları bu event konteynerinden yanıtlanıyorsa bu mod aktiftir."
        )
    else:
        socket_line = (
            "• *Socket Mode* bu süreçte *kapalı*; zamanlayıcı ve arka plan görevleri çalışıyor.\n"
            "• Slash komutları ana *challenge* sürecindeki socket üzerinden işlenir (Compose varsayılanı)."
        )

    text = (
        f"{ADMIN_STATUS_DIVIDER}\n"
        "*Event (etkinlik) servisi* — başlatıldı\n"
        f"{ADMIN_STATUS_DIVIDER}\n"
        "• Veritabanı bağlantı havuzu kullanılabilir.\n"
        "• Periyodik zamanlayıcı *çalışıyor* (~60 sn): zaman aşımı, sabah duyurusu, 10 dk öncesi hatırlatma, "
        "tamamlanmış etkinlik geçişleri.\n"
        f"{socket_line}"
    )
    try:
        slack_client.bot_client.chat_postMessage(channel=admin_channel, text=text)
        _logger.info("[NOTIFY] event service startup admin post sent")
    except Exception as exc:
        _logger.warning("[NOTIFY] event startup admin post failed: %s", exc)


def notify_event_service_shutdown(*, socket_bound: bool) -> None:
    """Event süreci dururken admin kanalına kısa kapanış bildirimi."""
    s = get_settings()
    admin_channel = (s.slack_admin_channel or "").strip()
    if not admin_channel:
        return

    sock_note = (
        "• Bu süreçte açık olan Socket kapatılıyor."
        if socket_bound
        else "• Bu süreçte Socket kullanılmıyordu (yalnızca zamanlayıcı / arka plan)."
    )
    sd_text = (
        f"{ADMIN_STATUS_DIVIDER}\n"
        "*Event (etkinlik) servisi* — kapatılıyor / durduruldu\n"
        f"{ADMIN_STATUS_DIVIDER}\n"
        "• Periyodik zamanlayıcı iptal edilip süreç sonlandırılıyor; Postgres oturumu kapatılıyor.\n"
        f"{sock_note}"
    )
    try:
        slack_client.bot_client.chat_postMessage(channel=admin_channel, text=sd_text)
        _logger.info("[NOTIFY] event service shutdown admin post sent")
    except Exception as exc:
        _logger.warning("[NOTIFY] event shutdown admin post failed: %s", exc)
