# -*- coding: utf-8 -*-
"""Персистентность продукта (Stage B3).

Одна таблица AnalysisSession: статусы пайплайна + JSON-колонки с
evidence-отчётом движка и CoachReport. Легаси-модели прямого VLM-пути
(AnalysisReport/CoachingTip и т.п.) удалены вместе с vlm_client.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, TypeDecorator
from sqlmodel import Field, Session, SQLModel, create_engine, select

# Жизненный цикл сессии: PENDING -> DETECTING -> MEASURING -> COACHING ->
# COMPLETED | FAILED. При coach_failed сессия всё равно COMPLETED —
# у игрока остаётся отчёт движка без коуч-текста (частичный результат).


def normalize_database_url(url: str) -> str:
    """postgres:// и postgresql:// (Neon/Supabase/Heroku-стиль) ->
    postgresql+psycopg:// — иначе SQLAlchemy тянет psycopg2, которого нет."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class UTCDateTime(TypeDecorator):
    """Даты всегда aware-UTC на любом диалекте.

    Postgres с naive-колонкой молча терял бы UTC; SQLite отдаёт naive даже
    при timezone=True — навешиваем tzinfo при чтении сами.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class User(SQLModel, table=True):
    """Аккаунт (Discord OAuth); паролей нет и не будет."""
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    discord_id: str = Field(index=True, unique=True)
    username: str
    avatar: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime()))


class AnalysisSession(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    video_path: str
    player_id: str                     # людей не сливаем — id обязателен
    clip_id: str                       # stem исходного файла (идемпотентность профиля)
    owner_user_id: Optional[UUID] = Field(default=None, index=True)
    share_token: Optional[str] = None  # явный шеринг отчёта (Этап 2)
    status: str = "PENDING"
    evidence_report: Optional[str] = None   # JSON движка (schema 1.1)
    coach_report: Optional[str] = None      # JSON CoachReport (None при провале)
    coach_failed: bool = False
    coach_errors: Optional[str] = None      # JSON-список ошибок groundedness
    evidence_frames: Optional[str] = None   # JSON-список URL кадров-улик
    error: Optional[str] = None             # причина FAILED
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime()))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime()))


class DatabaseManager:
    def __init__(self, db_url: str = "sqlite:///./aim_coach.db"):
        db_url = normalize_database_url(db_url)
        # pool_pre_ping: воркер живёт часами, Postgres-коннект может протухнуть.
        self.engine = create_engine(db_url, echo=False, pool_pre_ping=True)
        self._init_db()

    def _init_db(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    def create_session(self, video_path: str, *, player_id: str,
                       clip_id: str,
                       owner_user_id: Optional[UUID] = None) -> AnalysisSession:
        with Session(self.engine) as session:
            analysis_session = AnalysisSession(
                video_path=video_path, player_id=player_id, clip_id=clip_id,
                owner_user_id=owner_user_id)
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

    def get_or_create_discord_user(self, *, discord_id: str, username: str,
                                   avatar: Optional[str]) -> User:
        """Upsert по discord_id: повторный логин обновляет ник/аватар."""
        with Session(self.engine) as session:
            user = session.exec(
                select(User).where(User.discord_id == discord_id)).first()
            if user is None:
                user = User(discord_id=discord_id, username=username,
                            avatar=avatar)
            else:
                user.username = username
                user.avatar = avatar
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    def get_user(self, user_id: UUID) -> Optional[User]:
        with Session(self.engine) as session:
            return session.get(User, user_id)

    def count_sessions_since(self, owner_user_id: UUID,
                             since: datetime) -> int:
        """Сколько разборов аккаунт создал с момента since (квота free-тира)."""
        from sqlalchemy import func

        with Session(self.engine) as session:
            return session.exec(
                select(func.count())
                .select_from(AnalysisSession)
                .where(AnalysisSession.owner_user_id == owner_user_id)
                .where(AnalysisSession.created_at >= since)).one()

    def list_sessions_for_player(self, player_id: str,
                                 owner_user_id: Optional[UUID] = None):
        # Порядок отдаёт SQL (2C): история прогресса не должна зависеть от
        # порядка вставки/прихотей планировщика БД. Разрез по владельцу:
        # «friend» у двух аккаунтов — разные люди (Этап 2).
        with Session(self.engine) as session:
            query = (select(AnalysisSession)
                     .where(AnalysisSession.player_id == player_id)
                     .order_by(AnalysisSession.created_at))
            if owner_user_id is None:
                query = query.where(AnalysisSession.owner_user_id.is_(None))
            else:
                query = query.where(
                    AnalysisSession.owner_user_id == owner_user_id)
            return list(session.exec(query).all())
