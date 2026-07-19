# -*- coding: utf-8 -*-
"""Этап 1 запуска: БД готова к Postgres, dev остаётся на SQLite.

Живой Postgres в тестах не нужен: проверяем нормализацию URL (Neon/Supabase
дают postgres://, SQLAlchemy 2 + psycopg3 хотят postgresql+psycopg://),
timezone-aware даты (на Postgres naive-колонка молча теряет UTC) и
применимость alembic-миграций с нуля.
"""
from datetime import timezone

from sqlalchemy import inspect

from backend.database import DatabaseManager, normalize_database_url


# ------------------------------------------------------- нормализация URL

def test_postgres_scheme_upgraded_to_psycopg():
    assert (normalize_database_url("postgres://u:p@host/db")
            == "postgresql+psycopg://u:p@host/db")


def test_postgresql_scheme_upgraded_to_psycopg():
    assert (normalize_database_url("postgresql://u:p@host/db")
            == "postgresql+psycopg://u:p@host/db")


def test_explicit_driver_and_sqlite_untouched():
    assert (normalize_database_url("postgresql+psycopg://u@h/db")
            == "postgresql+psycopg://u@h/db")
    assert (normalize_database_url("sqlite:///./x.db")
            == "sqlite:///./x.db")


# ------------------------------------------------------------ tz-aware даты

def test_created_at_roundtrips_as_utc_aware(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'tz.db'}")
    session = db.create_session("v.mp4", player_id="p", clip_id="c")
    got = db.get_session(session.id)
    assert got.created_at.tzinfo is not None
    assert got.created_at.utcoffset() == timezone.utc.utcoffset(None)


# ---------------------------------------------------------------- alembic

def test_alembic_upgrade_head_creates_schema(tmp_path):
    """Чистая БД поднимается миграциями — путь прода, без create_all."""
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    cfg = Config("alembic.ini")
    cfg.attributes["sqlalchemy_url"] = url    # побеждает DATABASE_URL из .env
    command.upgrade(cfg, "head")

    from sqlalchemy import create_engine
    inspector = inspect(create_engine(url))
    columns = {c["name"] for c in inspector.get_columns("analysissession")}
    assert {"id", "video_path", "player_id", "clip_id", "status",
            "evidence_report", "coach_report", "coach_failed",
            "coach_errors", "evidence_frames", "error",
            "created_at", "updated_at"} <= columns


def test_alembic_schema_accepts_database_manager_writes(tmp_path):
    """Миграция и модель не разъехались: пишем через DatabaseManager."""
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{tmp_path / 'compat.db'}"
    cfg = Config("alembic.ini")
    cfg.attributes["sqlalchemy_url"] = url
    command.upgrade(cfg, "head")

    db = DatabaseManager(url)
    session = db.create_session("v.mp4", player_id="p", clip_id="c")
    db.update_session(session.id, status="COMPLETED",
                      evidence_report='{"ok": 1}')
    assert db.get_session(session.id).status == "COMPLETED"
