# -*- coding: utf-8 -*-
"""SteamID64 на аккаунте + снапшот внешнего бенчмарка на сессии.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("steam_id", sa.String(), nullable=True))
    op.add_column("analysissession",
                  sa.Column("external_benchmark", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysissession", "external_benchmark")
    op.drop_column("user", "steam_id")
