# -*- coding: utf-8 -*-
"""Персистентность продукта (Stage B3).

Одна таблица AnalysisSession: статусы пайплайна + JSON-колонки с
evidence-отчётом движка и CoachReport. Легаси-модели прямого VLM-пути
(AnalysisReport/CoachingTip и т.п.) удалены вместе с vlm_client.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Session, SQLModel, create_engine, select

# Жизненный цикл сессии: PENDING -> DETECTING -> MEASURING -> COACHING ->
# COMPLETED | FAILED. При coach_failed сессия всё равно COMPLETED —
# у игрока остаётся отчёт движка без коуч-текста (частичный результат).


class AnalysisSession(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    video_path: str
    player_id: str                     # людей не сливаем — id обязателен
    clip_id: str                       # stem исходного файла (идемпотентность профиля)
    status: str = "PENDING"
    evidence_report: Optional[str] = None   # JSON движка (schema 1.1)
    coach_report: Optional[str] = None      # JSON CoachReport (None при провале)
    coach_failed: bool = False
    coach_errors: Optional[str] = None      # JSON-список ошибок groundedness
    evidence_frames: Optional[str] = None   # JSON-список URL кадров-улик
    error: Optional[str] = None             # причина FAILED
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))


class DatabaseManager:
    def __init__(self, db_url: str = "sqlite:///./aim_coach.db"):
        self.engine = create_engine(db_url, echo=False)
        self._init_db()

    def _init_db(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    def create_session(self, video_path: str, *, player_id: str,
                       clip_id: str) -> AnalysisSession:
        with Session(self.engine) as session:
            analysis_session = AnalysisSession(
                video_path=video_path, player_id=player_id, clip_id=clip_id)
            session.add(analysis_session)
            session.commit()
            session.refresh(analysis_session)
            return analysis_session

    def update_session(self, session_id: UUID, **kwargs) -> AnalysisSession:
        with Session(self.engine) as session:
            db_session = session.get(AnalysisSession, session_id)
            if not db_session:
                raise ValueError(f"Session {session_id} not found")

            for key, value in kwargs.items():
                setattr(db_session, key, value)

            db_session.updated_at = datetime.now(timezone.utc)
            session.add(db_session)
            session.commit()
            session.refresh(db_session)
            return db_session

    def get_session(self, session_id: UUID) -> Optional[AnalysisSession]:
        with Session(self.engine) as session:
            return session.get(AnalysisSession, session_id)

    def list_sessions_for_player(self, player_id: str):
        # Порядок отдаёт SQL (2C): история прогресса не должна зависеть от
        # порядка вставки/прихотей планировщика БД.
        with Session(self.engine) as session:
            return list(session.exec(
                select(AnalysisSession)
                .where(AnalysisSession.player_id == player_id)
                .order_by(AnalysisSession.created_at)).all())
