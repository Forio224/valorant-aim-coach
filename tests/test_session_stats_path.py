# -*- coding: utf-8 -*-
"""Путь к логу тренажёра на сессии.

Поле нужно не пайплайну — тот получает путь через задачу, — а обозримости:
по завершённой сессии должно быть видно, разбирался клип с логом или без,
и переразбор того же клипа не должен требовать повторной загрузки файла.
"""
from backend.database import AnalysisSession, DatabaseManager


def _db(tmp_path):
    return DatabaseManager(f"sqlite:///{tmp_path / 'test.db'}")


def test_session_stores_stats_path(tmp_path):
    db = _db(tmp_path)
    session = db.create_session("clip.mp4", player_id="friend",
                                clip_id="clip", stats_path="uploads/a-stats.csv")
    assert session.stats_path == "uploads/a-stats.csv"


def test_stats_path_defaults_to_none(tmp_path):
    db = _db(tmp_path)
    session = db.create_session("clip.mp4", player_id="friend", clip_id="clip")
    assert session.stats_path is None


def test_stats_path_survives_reload(tmp_path):
    from sqlmodel import Session, select

    db = _db(tmp_path)
    created = db.create_session("clip.mp4", player_id="friend",
                                clip_id="clip", stats_path="uploads/x.csv")
    with Session(db.engine) as session:
        loaded = session.exec(
            select(AnalysisSession).where(
                AnalysisSession.id == created.id)).one()
    assert loaded.stats_path == "uploads/x.csv"
