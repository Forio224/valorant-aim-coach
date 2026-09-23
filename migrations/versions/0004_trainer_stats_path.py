# -*- coding: utf-8 -*-
"""Путь к логу аим-тренажёра на сессии.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysissession",
                  sa.Column("stats_path", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysissession", "stats_path")
