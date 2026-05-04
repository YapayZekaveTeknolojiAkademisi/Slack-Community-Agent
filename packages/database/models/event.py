from __future__ import annotations

from enum import Enum as PyEnum
from datetime import date, time
from sqlalchemy import Date, ForeignKey, Integer, String, Text, Time, UniqueConstraint, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.database.mixins import Base, IDMixin, TimestampMixin


class EventStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class LocationType(str, PyEnum):
    SLACK_CHANNEL = "slack_channel"
    ZOOM = "zoom"
    YOUTUBE = "youtube"
    GOOGLE_MEET = "google_meet"
    DISCORD = "discord"
    OTHER = "other"


class Event(Base, IDMixin, TimestampMixin):
    __tablename__ = "events"
    __prefix__ = "EVT"

    creator_slack_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    location_type: Mapped[LocationType] = mapped_column(
        SAEnum(LocationType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    yzta_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EventStatus] = mapped_column(
        SAEnum(EventStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False, index=True,
    )
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    interests: Mapped[list["EventInterest"]] = relationship("EventInterest", back_populates="event")


class EventInterest(Base, IDMixin, TimestampMixin):
    __tablename__ = "event_interest"
    __prefix__ = "EVI"
    __table_args__ = (
        UniqueConstraint("event_id", "slack_id", name="uq_event_interest_event_user"),
    )

    event_id: Mapped[str] = mapped_column(String(60), ForeignKey("events.id"), nullable=False, index=True)
    slack_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    event: Mapped["Event"] = relationship("Event", back_populates="interests")
