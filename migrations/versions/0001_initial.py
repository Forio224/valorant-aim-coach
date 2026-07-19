# -*- coding: utf-8 -*-
"""Начальная схема: analysissession (Stage B3 + Этап 1 запуска).

Revision ID: 0001
Revises:
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

from backend.database import UTCDateTime

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysissession",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("video_path", sa.String(), nullable=False),
        sa.Column("player_id", sa.String(), nullable=False),
        sa.Column("clip_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("evidence_report", sa.String(), nullable=True),
        sa.Column("coach_report", sa.String(), nullable=True),
        sa.Column("coach_failed", sa.Boolean(), nullable=False),
        sa.Column("coach_errors", sa.String(), nullable=True),
        sa.Column("evidence_frames", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=True),
    )
    # Поллинг фронта идёт по id (PK); история игрока — по player_id+created_at.
    op.create_index("ix_analysissession_player_created", "analysissession",
                    ["player_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_analysissession_player_created",
                  table_name="analysissession")
    op.drop_table("analysissession")
