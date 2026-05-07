from __future__ import annotations

from enum import Enum as PyEnum
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.database.mixins import Base, IDMixin, TimestampMixin


class ChallengeCategory(str, PyEnum):
    LEARN = "learn"
    PRACTICE = "practice"
    REAL_WORLD = "real_world"
    NO_CODE_LOW_CODE = "no_code_low_code"


class ChallengeStatus(str, PyEnum):
    NOT_STARTED = "not_started"                 # Takımlaştırma (henüz başlamadı / toplanıyor)
    STARTED = "started"                         # Challenge (geliştirme süreci)
    COMPLETED = "completed"                     # Tamamlandı (teslim edildi; jüri bekleniyor veya değerlendirme sürüyor)
    NOT_COMPLETED = "not_completed"             # Tamamlanmadı (süre doldu / çekildi)
    IN_EVALUATION = "in_evaluation"             # Değerlendirme süreci
    EVALUATED = "evaluated"                     # Değerlendirildi (puanlama / değerlendirme kaydı tamam)
    EVALUATION_DELAYED = "evaluation_delayed"   # Değerlendirme gecikti


class ChallengeType(Base, IDMixin, TimestampMixin):
    __tablename__ = "challenge_types"
    __prefix__ = "CHT"

    category: Mapped[ChallengeCategory] = mapped_column(
        SAEnum(ChallengeCategory, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=72,
        comment="Challenge şablonunun ödül / ağırlık puanı (seeds içinde kategoriye göre)",
    )
    checklist: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="Projenin kabul edilmesi için tamamlanması gereken adımlar (string listesi)")
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Challenge(Base, IDMixin, TimestampMixin):
    __tablename__ = "challenges"
    __prefix__ = "CHL"

    challenge_type_id: Mapped[str | None] = mapped_column(String(60), ForeignKey("challenge_types.id"), nullable=True, index=True)
    creator_slack_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[ChallengeStatus] = mapped_column(
        SAEnum(ChallengeStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )

    challenge_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    challenge_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    challenge_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    evaluation_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evaluation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluation_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    evaluation_results: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evaluation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    challenge_type: Mapped["ChallengeType | None"] = relationship("ChallengeType", foreign_keys=[challenge_type_id], lazy="noload")
    challenge_team_members: Mapped[list["ChallengeTeamMember"]] = relationship("ChallengeTeamMember", back_populates="challenge")
    challenge_jury_members: Mapped[list["ChallengeJuryMember"]] = relationship("ChallengeJuryMember", back_populates="challenge")


class ChallengeTeamMember(Base, IDMixin, TimestampMixin):
    __tablename__ = "challenge_team_members"
    __prefix__ = "CTM"

    challenge_id: Mapped[str] = mapped_column(String(60), ForeignKey("challenges.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(60), ForeignKey("slack_users.id"), nullable=True, index=True)
    slack_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    challenge: Mapped["Challenge"] = relationship("Challenge", back_populates="challenge_team_members")


class ChallengeJuryMember(Base, IDMixin, TimestampMixin):
    __tablename__ = "challenge_jury_members"
    __prefix__ = "CJM"

    challenge_id: Mapped[str] = mapped_column(String(60), ForeignKey("challenges.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(60), ForeignKey("slack_users.id"), nullable=True, index=True)
    slack_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    challenge: Mapped["Challenge"] = relationship("Challenge", back_populates="challenge_jury_members")


