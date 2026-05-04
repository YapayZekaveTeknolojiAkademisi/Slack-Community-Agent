"""
Feature Request Modelleri

/cemilimyapar komutuyla toplanan özellik taleplerini ve bu taleplerin clustering sonuçlarını veritabanında saklar.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.database.mixins import Base, IDMixin, TimestampMixin

if TYPE_CHECKING:
    from packages.database.models.slack import SlackUser


class FeatureRequest(Base, IDMixin, TimestampMixin):
    """
    Kullanıcılardan gelen tekil özellik talebi.
    """

    __tablename__ = "feature_requests"
    __prefix__ = "FRQ"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("slack_users.slack_id"), nullable=False, index=True
    )
    request_raw: Mapped[str] = mapped_column(Text, nullable=False)
    request_embedded: Mapped[list[float] | None] = mapped_column(
        Vector(768), nullable=True
    )

    # embedded | clustered | reported | embedding_failed | clustering_failed
    status: Mapped[str] = mapped_column(
        String, default="embedded", nullable=False, index=True
    )

    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fraud_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    user: Mapped["SlackUser"] = relationship("SlackUser", backref="feature_requests")

    def __repr__(self) -> str:
        return (
            f"<FeatureRequest(id={self.id!r}, "
            f"user_id={self.user_id!r}, "
            f"status={self.status!r}, "
            f"cluster_id={self.cluster_id!r})>"
        )


class FeatureClusterLabel(Base, IDMixin, TimestampMixin):
    """
    HDBSCAN tarafından oluşturulan kümelerin (cluster) LLM ile isimlendirilmiş hali.
    """

    __tablename__ = "feature_cluster_labels"
    __prefix__ = "FCL"

    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    report_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<FeatureClusterLabel(id={self.id!r}, "
            f"cluster_id={self.cluster_id!r}, "
            f"label={self.label!r})>"
        )
