"""
Event Service — Background scheduler.
Periyodik gorevler:
  1. Timeout: PENDING + event_approval_timeout_hours (varsayilan 72 saat) → REJECTED
  2. Gun basi hatirlatma: O gunun etkinliklerini duyur
  3. 10dk oncesi hatirlatma
  4. COMPLETED gecisi: Tarihi gecmis APPROVED → COMPLETED
"""
from __future__ import annotations

import asyncio
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from packages.database.manager import db
from packages.database.models.event import Event, EventStatus
from packages.database.repository.event import EventRepository, EventInterestRepository
from packages.settings import get_settings
from packages.slack.blocks.builder import MessageBuilder
from packages.slack.client import slack_client
from ..logger import _logger
from ..utils.notifications import (
    get_announcement_channels,
    send_dm,
    _location_display,
    _calendar_url,
    update_admin_request_message,
)
from ..utils.email import send_reminder_email_async, send_user_status_email_async


def _local_tz() -> ZoneInfo:
    """Etkinlik saatlerinin yorumlanacagi yerel timezone (settings'ten)."""
    return ZoneInfo(get_settings().event_timezone)


def _now_local() -> datetime:
    """Yerel timezone'da simdiki zaman (timezone-aware)."""
    return datetime.now(_local_tz())


async def _io_slack_chat_post(channel: str, text: str, blocks: list) -> None:
    """Senkron Slack Web API çağrısını thread'de çalıştırır — asyncio döngüsünü bloklamaz."""

    def _sync() -> None:
        slack_client.bot_client.chat_postMessage(channel=channel, text=text, blocks=blocks)

    await asyncio.to_thread(_sync)


class EventScheduler:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._morning_reminder_last_date: date | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        _logger.info("[SCHED] Event scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("[SCHED] Event scheduler stopped")

    async def _run_loop(self) -> None:
        """Her 60 saniyede bir tum gorevleri calistirir."""
        while self._running:
            try:
                await self._check_pending_timeout()
                await self._check_completed_transition()
                await self._check_morning_reminder()
                await self._check_10min_reminder()
            except Exception as e:
                _logger.error("[SCHED] Error in loop: %s", e, exc_info=True)
            await asyncio.sleep(60)

    # ---- 1. Timeout: PENDING + event_approval_timeout_hours → REJECTED ----

    async def _check_pending_timeout(self) -> None:
        s = get_settings()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=s.event_approval_timeout_hours)

        async with db.session() as session:
            repo = EventRepository(session)
            expired = await repo.list_pending_expired(cutoff)
            for evt in expired:
                evt.status = EventStatus.REJECTED
                _logger.info("[SCHED] Timeout: %s", evt.id)
                dm_text = (
                    f"Etkinlik Talebiniz Zaman Aşımına Uğradı\n\n"
                    f"*{evt.name}*\n"
                    f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')}\n\n"
                    f"Talebiniz {s.event_approval_timeout_hours // 24} gün içinde yanıt alamadığı için "
                    f"otomatik olarak reddedildi.\n\n"
                    f"Yeni bir etkinlik talebi için `/event create` komutunu kullanabilirsiniz.\n_{evt.id}_"
                )
                try:
                    await asyncio.to_thread(send_dm, evt.creator_slack_id, dm_text)
                except Exception as e:
                    _logger.warning("[SCHED] Timeout Slack DM failed event=%s: %s", evt.id, e)
                try:
                    await send_user_status_email_async(evt.creator_slack_id, evt, "timeout")
                except Exception as e:
                    _logger.warning("[SCHED] Timeout e-posta failed event=%s: %s", evt.id, e)
                try:
                    await asyncio.to_thread(
                        update_admin_request_message,
                        evt,
                        outcome="timeout",
                        admin_id=None,
                        note=None,
                    )
                except Exception as e:
                    _logger.warning("[SCHED] Timeout admin message update failed event=%s: %s", evt.id, e)

    # ---- 2. COMPLETED gecisi ----

    async def _check_completed_transition(self) -> None:
        # Yerel tarihe gore gecmiste kalan etkinlikleri COMPLETED'a cek
        local_today = _now_local().date()
        async with db.session() as session:
            repo = EventRepository(session)
            past = await repo.list_approved_past(local_today)
            for evt in past:
                evt.status = EventStatus.COMPLETED
                _logger.info("[SCHED] Completed: %s", evt.id)

    # ---- 3. Gun basi hatirlatma ----

    async def _check_morning_reminder(self) -> None:
        """Her gun yerel TZ'de ayarlanan saatte (default 08:00) o gunun etkinliklerini duyurur.
        Gun basina 1 kez calisir (tarih flag'i ile kontrol edilir).
        """
        s = get_settings()
        now_local = _now_local()
        local_today = now_local.date()

        # Ayarlanan saatten once calisma
        if now_local.hour < s.event_morning_reminder_hour:
            return

        # Bugun zaten gonderildiyse atla
        if self._morning_reminder_last_date == local_today:
            return

        if not s.event_reminder_enabled:
            return

        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            events = await repo.list_approved_by_date(local_today)
            if not events:
                self._morning_reminder_last_date = local_today
                return

            interest_repo = EventInterestRepository(session)

            builder = MessageBuilder()
            builder.add_header(f"Bugünün Etkinlikleri — {local_today.strftime('%d %B %Y')}")
            builder.add_divider()

            # E-posta gonderilecek ilgili kullanicilari topla
            interested_users: list[tuple[str, Event]] = []

            for i, evt in enumerate(events, 1):
                loc = _location_display(evt)
                count = await interest_repo.count_by_event(evt.id)
                cal_url = await asyncio.to_thread(_calendar_url, evt)

                builder.add_text(
                    f"*{i}. {evt.name}*\n"
                    f"{evt.time.strftime('%H:%M')} · {evt.duration_minutes} dk · {loc}\n"
                    f"<@{evt.creator_slack_id}> · {count} kişi ilgi gösterdi"
                )
                if evt.link:
                    builder.add_button("Katıl", f"event_link_{evt.id}", url=evt.link)
                builder.add_button("Google Takvime Ekle", f"event_cal_{evt.id}", url=cal_url)
                builder.add_divider()

                # Ilgi gosterenleri topla
                interests = await interest_repo.list_by_event(evt.id)
                for interest in interests:
                    interested_users.append((interest.slack_id, evt))

            builder.add_context(["_İyi etkinlikler!_"])
            blocks = builder.build()

            # Tum duyuru kanallarini topla (tekrarsiz)
            all_channels: set[str] = set()
            for evt in events:
                all_channels.update(get_announcement_channels(evt))

            for ch in all_channels:
                try:
                    await _io_slack_chat_post(
                        ch,
                        f"Bugünün Etkinlikleri — {local_today.strftime('%d %B %Y')}",
                        blocks,
                    )
                except Exception as e:
                    _logger.error("[SCHED] Morning reminder failed channel=%s: %s", ch, e)

        # E-posta gonder (read session kapandiktan sonra)
        for slack_id, evt in interested_users:
            try:
                await send_reminder_email_async(slack_id, evt, "day")
            except Exception as e:
                _logger.warning("[SCHED] Morning reminder email skipped slack_id=%s: %s", slack_id, e)

        self._morning_reminder_last_date = local_today
        _logger.info("[SCHED] Morning reminder sent for %d events", len(events))

    # ---- 4. 10dk oncesi hatirlatma ----

    async def _check_10min_reminder(self) -> None:
        s = get_settings()
        if not s.event_reminder_enabled:
            return

        # Etkinlik saatleri YEREL TZ'de yorumlanir — kullanici yerel saat girer.
        tz = _local_tz()
        now_local = _now_local()
        local_today = now_local.date()

        # Bildirim gonderilecek event'leri ve ilgili kullanicilari topla
        to_notify: list[tuple[Event, list[str]]] = []
        events_to_mark: list[str] = []

        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            events = await repo.list_approved_by_date(local_today)

            interest_repo = EventInterestRepository(session)

            for evt in events:
                # Etkinlik zamani = yerel tarih + yerel saat (timezone-aware)
                evt_dt = datetime.combine(local_today, evt.time, tzinfo=tz)
                diff = (evt_dt - now_local).total_seconds()
                if not (540 <= diff <= 660):  # 9-11 dakika arasi
                    continue

                meta = evt.meta or {}
                if meta.get("10min_reminder_sent"):
                    continue

                # Ilgi gosterenleri topla
                interests = await interest_repo.list_by_event(evt.id)
                interested_ids = [i.slack_id for i in interests]
                to_notify.append((evt, interested_ids))
                events_to_mark.append(evt.id)

        # Slack bildirimleri gonder (read session kapalı)
        for evt, interested_ids in to_notify:
            loc = _location_display(evt)
            count = len(interested_ids)
            cal_url = await asyncio.to_thread(_calendar_url, evt)

            builder = MessageBuilder()
            builder.add_header("10 Dakika Sonra Başlıyor!")
            builder.add_text(
                f"*{evt.name}*\n\n"
                f"*Saat:* {evt.time.strftime('%H:%M')}\n"
                f"*Süre:* {evt.duration_minutes} dakika\n"
                f"*Lokasyon:* {loc}\n"
                f"*Düzenleyen:* <@{evt.creator_slack_id}>\n"
                f"*İlgi:* {count} kişi"
            )
            if evt.link:
                builder.add_button("Katıl", "event_10min_link", url=evt.link)
            builder.add_button("Google Takvime Ekle", "event_10min_cal", url=cal_url)

            blocks = builder.build()
            for ch in get_announcement_channels(evt):
                try:
                    await _io_slack_chat_post(
                        ch,
                        f"10 Dakika Sonra: {evt.name}",
                        blocks,
                    )
                except Exception as e:
                    _logger.error("[SCHED] 10min reminder failed channel=%s: %s", ch, e)

            # E-posta gonder
            for slack_id in interested_ids:
                try:
                    await send_reminder_email_async(slack_id, evt, "10min")
                except Exception as e:
                    _logger.warning("[SCHED] 10min reminder email skipped slack_id=%s: %s", slack_id, e)

            _logger.info("[SCHED] 10min reminder sent: %s", evt.id)

        # Meta guncelle (ayri write session)
        if events_to_mark:
            async with db.session() as write_session:
                for event_id in events_to_mark:
                    write_evt = await write_session.get(Event, event_id)
                    if write_evt:
                        m = dict(write_evt.meta or {})
                        m["10min_reminder_sent"] = True
                        write_evt.meta = m


event_scheduler = EventScheduler()
