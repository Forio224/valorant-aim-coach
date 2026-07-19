# -*- coding: utf-8 -*-
"""Аккаунты и владение сессиями (Этап 2 запуска).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

from backend.database import UTCDateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("discord_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("avatar", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=True),
    )
    op.create_index("ix_user_discord_id", "user", ["discord_id"], unique=True)
    op.add_column("analysissession",
                  sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.add_column("analysissession",
                  sa.Column("share_token", sa.String(), nullable=True))
    op.create_index("ix_analysissession_owner_user_id", "analysissession",
                    ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_analysissession_owner_user_id",
                  table_name="analysissession")
    op.drop_column("analysissession", "share_token")
    op.drop_column("analysissession", "owner_user_id")
    op.drop_index("ix_user_discord_id", table_name="user")
    op.drop_table("user")
