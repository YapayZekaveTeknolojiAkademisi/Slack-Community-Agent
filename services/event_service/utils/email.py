"""Event Service — E-posta bildirim yardimcilari.

Sync fonksiyonlar: Bolt handler thread'lerinden cagirilir (_resolve_email → run_async).
Async fonksiyonlar: Scheduler'dan cagirilir (_resolve_email_async → dogrudan await).
"""
from __future__ import annotations

from packages.database.manager import db
from packages.database.repository.slack import SlackUserRepository
from packages.settings import get_settings
from packages.smtp.client import SmtpClient
from packages.smtp.schema import EmailMessage
from packages.database.models.event import Event, LocationType
from ..logger import _logger


def _admin_email_recipients() -> list[str]:
    """ADMIN_EMAIL virgülle ayrılmış olabilir — EmailMessage ``to`` alanı list[str] bekler."""
    raw = (get_settings().admin_email or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _get_smtp() -> SmtpClient | None:
    """SMTP client döner; yapılandırma/bağlantı hatasında None — servis akışı kesilmez."""
    if not get_settings().smtp_enabled:
        return None
    try:
        return SmtpClient()
    except Exception as e:
        _logger.warning("[EVT-EMAIL] SMTP başlatılamadı, e-posta atlanıyor: %s", e)
        return None


def _location_label(event: Event) -> str:
    """E-posta icin okunabilir lokasyon metni."""
    loc = event.location_type
    display = {
        LocationType.SLACK_CHANNEL: "Slack Kanalı",
        LocationType.ZOOM: "Zoom",
        LocationType.YOUTUBE: "YouTube",
        LocationType.GOOGLE_MEET: "Google Meet",
        LocationType.DISCORD: "Discord",
        LocationType.OTHER: "Diğer",
    }
    return display.get(loc, str(loc))


# ---------------------------------------------------------------------------
# Email cozumleme — sync (Bolt handler'lar) ve async (scheduler) versiyonlari
# ---------------------------------------------------------------------------

def _resolve_email(slack_id: str) -> str | None:
    """SlackUser tablosundan e-posta adresini cekerler (sync — Bolt handler'lar icin)."""
    from services.event_service.core.event_loop import run_async

    async def _fetch():
        async with db.session(read_only=True) as session:
            repo = SlackUserRepository(session)
            user = await repo.get_by_slack_id(slack_id)
            return user.email if user else None

    try:
        return run_async(_fetch())
    except Exception as e:
        _logger.warning("[EVT-EMAIL] E-posta cozumlenemedi slack_id=%s: %s", slack_id, e)
        return None


async def _resolve_email_async(slack_id: str) -> str | None:
    """SlackUser tablosundan e-posta adresini cekerler (async — scheduler icin)."""
    try:
        async with db.session(read_only=True) as session:
            repo = SlackUserRepository(session)
            user = await repo.get_by_slack_id(slack_id)
            return user.email if user else None
    except Exception as e:
        _logger.warning("[EVT-EMAIL] E-posta cozumlenemedi slack_id=%s: %s", slack_id, e)
        return None


# ---------------------------------------------------------------------------
# Sync e-posta fonksiyonlari (Bolt handler'lardan cagirilir)
# ---------------------------------------------------------------------------

def send_admin_notification(event: Event) -> None:
    """Admin'e yeni etkinlik talebi e-postasi gonderir."""
    try:
        smtp = _get_smtp()
        admin_to = _admin_email_recipients()
        if not smtp or not admin_to:
            return
        loc_label = _location_label(event)
        subject = f"Yeni Etkinlik Talebi: {event.name}"
        body = (
            f"Etkinlik: {event.name}\n"
            f"Konu: {event.topic}\n"
            f"Açıklama: {event.description}\n"
            f"Tarih: {event.date} {event.time}\n"
            f"Süre: {event.duration_minutes} dakika\n"
            f"Lokasyon: {loc_label}\n"
            f"Link: {event.link or '—'}\n"
            f"YZTA Talep: {event.yzta_request or '—'}\n"
            f"Talep Eden: {event.creator_slack_id}\n"
        )
        msg = EmailMessage(to=admin_to, subject=subject, body=body)
        smtp.send(msg)
    except Exception as e:
        _logger.warning("[EVT-EMAIL] Admin bildirimi gönderilemedi (işlem sürüyor): %s", e)


def send_user_status_email(slack_id: str, event: Event, status: str, admin_note: str | None = None) -> None:
    """Kullaniciya onay/red/timeout e-postasi gonderir (sync)."""
    try:
        smtp = _get_smtp()
        if not smtp:
            return
        user_email = _resolve_email(slack_id)
        if not user_email:
            _logger.info("[EVT-EMAIL] E-posta bulunamadi, atlaniyor: slack_id=%s", slack_id)
            return
        _send_status_email(smtp, user_email, event, status, admin_note)
    except Exception as e:
        _logger.warning("[EVT-EMAIL] Kullanıcı durum e-postası atlanıyor: %s", e)


def send_cancellation_email(slack_id: str, event: Event) -> None:
    """Iptal bildirimi e-postasi gonderir (sync)."""
    try:
        smtp = _get_smtp()
        if not smtp:
            return
        user_email = _resolve_email(slack_id)
        if not user_email:
            return
        _send_cancellation(smtp, user_email, event)
    except Exception as e:
        _logger.warning("[EVT-EMAIL] İptal e-postası atlanıyor: %s", e)


def send_update_email(slack_id: str, event: Event) -> None:
    """Guncelleme bildirimi e-postasi gonderir (sync)."""
    try:
        smtp = _get_smtp()
        if not smtp:
            return
        user_email = _resolve_email(slack_id)
        if not user_email:
            return
        _send_update(smtp, user_email, event)
    except Exception as e:
        _logger.warning("[EVT-EMAIL] Güncelleme e-postası atlanıyor: %s", e)


# ---------------------------------------------------------------------------
# Async e-posta fonksiyonlari (scheduler'dan cagirilir — deadlock onlenir)
# ---------------------------------------------------------------------------

async def send_reminder_email_async(slack_id: str, event: Event, reminder_type: str = "day") -> None:
    """Hatirlatma e-postasi gonderir (async — scheduler icin)."""
    try:
        smtp = _get_smtp()
        if not smtp:
            return
        user_email = await _resolve_email_async(slack_id)
        if not user_email:
            return
        if reminder_type == "10min":
            subject = f"10 Dakika Sonra: {event.name}"
        else:
            subject = f"Bugün: {event.name}"
        body = (
            f"Etkinlik: {event.name}\n"
            f"Saat: {event.time.strftime('%H:%M')}\n"
            f"Süre: {event.duration_minutes} dakika\n"
            f"Link: {event.link or '—'}\n"
        )
        msg = EmailMessage(to=[user_email], subject=subject, body=body)
        smtp.send(msg)
    except Exception as e:
        _logger.warning("[EVT-EMAIL] Hatırlatma e-postası atlanıyor: %s", e)


async def send_user_status_email_async(slack_id: str, event: Event, status: str, admin_note: str | None = None) -> None:
    """Kullaniciya onay/red/timeout e-postasi gonderir (async — scheduler icin)."""
    try:
        smtp = _get_smtp()
        if not smtp:
            return
        user_email = await _resolve_email_async(slack_id)
        if not user_email:
            return
        _send_status_email(smtp, user_email, event, status, admin_note)
    except Exception as e:
        _logger.warning("[EVT-EMAIL] Zamanlayıcı durum e-postası atlanıyor: %s", e)


# ---------------------------------------------------------------------------
# Ortak e-posta gonderim yardimcilari (sync — SMTP kendisi sync)
# ---------------------------------------------------------------------------

def _send_status_email(smtp: SmtpClient, user_email: str, event: Event, status: str, admin_note: str | None) -> None:
    try:
        status_text = {"approved": "Onaylandı", "rejected": "Reddedildi", "timeout": "Zaman Aşımı"}.get(status, status)
        subject = f"Etkinlik {status_text}: {event.name}"
        body = (
            f"Etkinlik: {event.name}\n"
            f"Tarih: {event.date} {event.time}\n"
            f"Durum: {status_text}\n"
        )
        if admin_note:
            body += f"Admin Notu: {admin_note}\n"
        msg = EmailMessage(to=[user_email], subject=subject, body=body)
        smtp.send(msg)
    except Exception as e:
        _logger.error("[EVT-EMAIL] Kullanıcı bildirimi gönderilemedi: %s", e)


def _send_cancellation(smtp: SmtpClient, user_email: str, event: Event) -> None:
    try:
        subject = f"Etkinlik İptal Edildi: {event.name}"
        body = (
            f"Etkinlik: {event.name}\n"
            f"Tarih: {event.date} {event.time}\n"
            f"Bu etkinlik iptal edilmiştir.\n"
        )
        msg = EmailMessage(to=[user_email], subject=subject, body=body)
        smtp.send(msg)
    except Exception as e:
        _logger.error("[EVT-EMAIL] İptal bildirimi gönderilemedi: %s", e)


def _send_update(smtp: SmtpClient, user_email: str, event: Event) -> None:
    try:
        subject = f"Etkinlik Güncellendi: {event.name}"
        body = (
            f"Etkinlik: {event.name}\n"
            f"Tarih: {event.date} {event.time}\n"
            f"Süre: {event.duration_minutes} dakika\n"
            f"Link: {event.link or '—'}\n"
            f"Etkinlik bilgileri güncellenmiştir. Detaylar için Slack kanalını kontrol edin.\n"
        )
        msg = EmailMessage(to=[user_email], subject=subject, body=body)
        smtp.send(msg)
    except Exception as e:
        _logger.error("[EVT-EMAIL] Guncelleme bildirimi gonderilemedi: %s", e)
