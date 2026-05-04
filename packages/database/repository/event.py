from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, func

from packages.database.models.event import Event, EventInterest, EventStatus
from packages.database.repository.base import BaseRepository
from packages.settings import get_settings


def _today_in_event_timezone() -> date:
    tz = ZoneInfo(get_settings().event_timezone)
    return datetime.now(tz).date()


class EventRepository(BaseRepository[Event]):
    model = Event

    async def list_by_status(self, status: EventStatus) -> list[Event]:
        result = await self.session.execute(
            select(Event).where(Event.status == status).order_by(Event.date, Event.time)
        )
        return list(result.scalars().all())

    async def list_approved_by_date(self, target_date: date) -> list[Event]:
        """Belirli bir tarihteki APPROVED etkinlikleri doner."""
        result = await self.session.execute(
            select(Event)
            .where(Event.status == EventStatus.APPROVED, Event.date == target_date)
            .order_by(Event.time)
        )
        return list(result.scalars().all())

    async def list_current_month(self) -> list[Event]:
        """Bu ayin APPROVED etkinliklerini doner."""
        today = _today_in_event_timezone()
        first_day = today.replace(day=1)
        if today.month == 12:
            last_day = today.replace(year=today.year + 1, month=1, day=1)
        else:
            last_day = today.replace(month=today.month + 1, day=1)

        result = await self.session.execute(
            select(Event)
            .where(
                Event.status == EventStatus.APPROVED,
                Event.date >= first_day,
                Event.date < last_day,
            )
            .order_by(Event.date, Event.time)
        )
        return list(result.scalars().all())

    async def list_by_creator(self, slack_id: str) -> list[Event]:
        """Kullanicinin olusturdugu tum etkinlikler (aktif olanlar)."""
        result = await self.session.execute(
            select(Event)
            .where(
                Event.creator_slack_id == slack_id,
                Event.status.in_([EventStatus.PENDING, EventStatus.APPROVED]),
            )
            .order_by(Event.date.desc(), Event.time.desc())
        )
        return list(result.scalars().all())

    async def list_by_creator_and_status(self, slack_id: str, status: EventStatus) -> list[Event]:
        """Kullanicinin belirli statusdeki etkinlikleri."""
        result = await self.session.execute(
            select(Event)
            .where(Event.creator_slack_id == slack_id, Event.status == status)
            .order_by(Event.date, Event.time)
        )
        return list(result.scalars().all())

    async def list_history(self) -> list[Event]:
        """Gecmis etkinlikler (COMPLETED + CANCELLED)."""
        result = await self.session.execute(
            select(Event)
            .where(Event.status.in_([EventStatus.COMPLETED, EventStatus.CANCELLED]))
            .order_by(Event.date.desc(), Event.time.desc())
        )
        return list(result.scalars().all())

    async def list_pending_expired(self, cutoff_dt) -> list[Event]:
        """Suresi dolmus PENDING etkinlikler."""
        result = await self.session.execute(
            select(Event)
            .where(Event.status == EventStatus.PENDING, Event.created_at < cutoff_dt)
        )
        return list(result.scalars().all())

    async def list_approved_past(self, now_date: date) -> list[Event]:
        """Tarihi gecmis APPROVED etkinlikler (COMPLETED'a cekilecek)."""
        result = await self.session.execute(
            select(Event)
            .where(Event.status == EventStatus.APPROVED, Event.date < now_date)
        )
        return list(result.scalars().all())

    async def list_approved_for_interest_form(self, slack_id: str, days_ahead: int = 30) -> list[Event]:
        """
        /event add_me formu icin: onumuzdeki N gun icindeki APPROVED etkinlikleri
        doner, ancak kullanicinin daha once ilgi gostermedigi etkinlikleri filtreler.
        """
        today = _today_in_event_timezone()
        end_date = today + timedelta(days=days_ahead)

        # Kullanicinin ilgi gosterdigi event ID'leri (subquery)
        interested_subq = (
            select(EventInterest.event_id)
            .where(EventInterest.slack_id == slack_id)
        )

        result = await self.session.execute(
            select(Event)
            .where(
                Event.status == EventStatus.APPROVED,
                Event.date >= today,
                Event.date <= end_date,
                Event.id.not_in(interested_subq),
            )
            .order_by(Event.date, Event.time)
        )
        return list(result.scalars().all())


class EventInterestRepository(BaseRepository[EventInterest]):
    model = EventInterest

    async def find_by_event_and_user(self, event_id: str, slack_id: str) -> EventInterest | None:
        result = await self.session.execute(
            select(EventInterest)
            .where(EventInterest.event_id == event_id, EventInterest.slack_id == slack_id)
        )
        return result.scalar_one_or_none()

    async def count_by_event(self, event_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(EventInterest).where(EventInterest.event_id == event_id)
        )
        return result.scalar_one()

    async def list_by_event(self, event_id: str) -> list[EventInterest]:
        result = await self.session.execute(
            select(EventInterest).where(EventInterest.event_id == event_id)
        )
        return list(result.scalars().all())

    async def set_event_ids_by_user(self, slack_id: str) -> set[str]:
        """
        Kullanicinin ilgi gosterdigi tum event ID'lerini tek sorguyla doner.
        N+1 query pattern'ini onlemek icin list'lerde kullanilir.
        """
        result = await self.session.execute(
            select(EventInterest.event_id).where(EventInterest.slack_id == slack_id)
        )
        return {row[0] for row in result.all()}
