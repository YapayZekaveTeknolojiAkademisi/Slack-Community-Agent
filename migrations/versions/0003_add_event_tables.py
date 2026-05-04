"""Add event tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("creator_slack_id", sa.String(32), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("date", sa.Date, nullable=False, index=True),
        sa.Column("time", sa.Time, nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("location_type", sa.Enum("slack_channel", "zoom", "youtube", "google_meet", "discord", "other", name="locationtype"), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=True),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("yzta_request", sa.Text, nullable=True),
        sa.Column("status", sa.Enum("pending", "approved", "rejected", "cancelled", "completed", name="eventstatus"), nullable=False, index=True),
        sa.Column("admin_note", sa.Text, nullable=True),
        sa.Column("approved_by", sa.String(32), nullable=True),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "event_interest",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("event_id", sa.String(60), sa.ForeignKey("events.id"), nullable=False, index=True),
        sa.Column("slack_id", sa.String(32), nullable=False, index=True),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "slack_id", name="uq_event_interest_event_user"),
    )


def downgrade() -> None:
    op.drop_table("event_interest")
    op.drop_table("events")
    op.execute("DROP TYPE IF EXISTS eventstatus")
    op.execute("DROP TYPE IF EXISTS locationtype")
