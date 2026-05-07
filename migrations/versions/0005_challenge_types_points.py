"""challenge_types tablosuna puan (points) kolonu

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_POINTS = 72


def upgrade() -> None:
    op.add_column(
        "challenge_types",
        sa.Column(
            "points",
            sa.Integer(),
            nullable=False,
            server_default=str(_DEFAULT_POINTS),
        ),
    )
    op.alter_column("challenge_types", "points", server_default=None)


def downgrade() -> None:
    op.drop_column("challenge_types", "points")
