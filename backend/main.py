# -*- coding: utf-8 -*-
"""FastAPI поверх продуктового пайплайна (Stage B3).

upload -> фоновая задача run_pipeline (YOLO -> движок -> коуч) -> БД;
фронт поллит GET и получает evidence-отчёт + CoachReport + URL кадров-улик
(раздаются через /evidence StaticFiles). Легаси-путь «кадры -> Claude»
(vlm_client / services.video_processor) ретайрнут.
"""
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import (BackgroundTasks, FastAPI, File, Form, HTTPException,
                     Request, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import auth
from backend.database import DatabaseManager
from backend.services.analysis_pipeline import run_pipeline
from backend.services.analysis_task import AnalysisJob, run_analysis_session
from backend.services.history_provider import make_history_provider
from backend.services.clip_validation import (ClipValidationError,
                                              validate_clip)
from backend.services.job_queue import create_job_queue
from backend.services.rate_limit import enforce_upload_limit
from backend.services.storage import UPLOAD_PREFIX, create_storage

from backend.observability import init_sentry

load_dotenv()
logger = logging.getLogger(__name__)
init_sentry("api")

app = FastAPI(title="Valorant AI Aim Coach", version="2.0.0")
app.include_router(auth.router)

# CORS: только фронт; дополнительные origin — через env (через запятую).
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = DatabaseManager(os.getenv("DATABASE_URL", "sqlite:///./aim_coach.db"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
EVIDENCE_DIR = os.getenv("EVIDENCE_DIR", os.path.join(UPLOAD_DIR, "evidence"))

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EVIDENCE_DIR, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=EVIDENCE_DIR), name="evidence")

# STORAGE_BACKEND=local (дефолт) | r2 — см. services/storage.py.
storage = create_storage(evidence_dir=EVIDENCE_DIR)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Базовые заголовки безопасности; HSTS — только за HTTPS (прод)."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()")
    if os.getenv("SECURE_COOKIES", "0") == "1":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains")
    return response


def _enforce_daily_quota(user) -> None:
    """Квота free-тира (юнит-экономика: 3 клипа/день); аноним (dev) — без квоты."""
    if user is None:
        return
    from datetime import datetime, time as dtime, timezone

    quota = int(os.getenv("FREE_DAILY_CLIPS", "3"))
    day_start = datetime.combine(
        datetime.now(timezone.utc).date(), dtime.min, tzinfo=timezone.utc)
    used = db.count_sessions_since(user.id, day_start)
    if used >= quota:
        raise HTTPException(
            status_code=429,
            detail=f"Дневной лимит бесплатных разборов исчерпан "
                   f"({quota}/день). Новая квота — завтра по UTC.")

ALLOWED_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv")
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "300"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)


async def process_video_task(job: AnalysisJob) -> None:
    """Background-режим: разбор в executor процесса API (как раньше).

    run_pipeline берётся из глобали модуля на момент вызова — тесты
    подменяют main.run_pipeline фейком.
    """
    import uuid as _uuid

    owner = _uuid.UUID(job.owner_id) if job.owner_id else None
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_analysis_session(
        db, job, evidence_dir=EVIDENCE_DIR, pipeline=run_pipeline,
        history_provider=make_history_provider(db, owner_user_id=owner),
        storage=storage))


# QUEUE_BACKEND=background (дефолт) | arq — см. services/job_queue.py.
job_queue = create_job_queue(process_video_task)


def _validate_upload_meta(filename: str | None, player_id: str,
                          training_platform: str | None) -> str:
    """Общая валидация границы API (direct и presigned пути) -> player_id."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video format")
    # Валидация на границе API: иначе ValueError из ClipContext перехватится
    # пайплайном и отрапортуется игроку как ложное «файл повреждён».
    if training_platform not in (None, "kovaaks", "ingame"):
        raise HTTPException(
            status_code=422,
            detail="training_platform должен быть 'kovaaks' или 'ingame'")
    player_id = player_id.strip()
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    return player_id


async def _create_and_enqueue(background_tasks: BackgroundTasks, *,
                              video_ref: str, filename: str, player_id: str,
                              sens, edpi, agent, map_name,
                              training_platform, user=None) -> dict:
    # clip_id = stem исходного имени: повторная загрузка того же клипа
    # идемпотентно перезаписывает его в продольном профиле.
    clip_id = Path(filename).stem
    session = db.create_session(video_ref, player_id=player_id,
                                clip_id=clip_id,
                                owner_user_id=user.id if user else None)
    await job_queue.enqueue(background_tasks, AnalysisJob(
        session_id=str(session.id), video_path=video_ref,
        player_id=player_id, clip_id=clip_id, sens=sens, edpi=edpi,
        agent=agent, map_name=map_name, training_platform=training_platform,
        owner_id=str(user.id) if user else None))
    return {
        "session_id": str(session.id),
        "status": session.status,
        "message": "Клип загружен, анализ запущен.",
    }


@app.post("/api/v1/analysis/uploads")
async def create_upload(request: Request, filename: str = Form(...)):
    enforce_upload_limit(request)
    auth.require_user(request)
    """Шаг 1 presigned-флоу: куда грузить клип.

    local: {"mode": "direct"} — фронт шлёт файл в /upload, как раньше.
    r2: {"mode": "presigned", upload_url, key} — PUT напрямую в бакет,
    затем POST /start (300 МБ не идут через API).
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video format")
    presigned = storage.presign_upload(filename)
    if presigned is None:
        return {"mode": "direct"}
    return {"mode": "presigned", "max_upload_mb": MAX_UPLOAD_MB, **presigned}


@app.post("/api/v1/analysis/start")
async def start_analysis(request: Request,
                         background_tasks: BackgroundTasks,
                         key: str = Form(...),
                         filename: str = Form(...),
                         player_id: str = Form(...),
                         sens: float | None = Form(None),
                         edpi: float | None = Form(None),
                         agent: str | None = Form(None),
                         map_name: str | None = Form(None),
                         training_platform: str | None = Form(None)):
    """Шаг 2 presigned-флоу: клип уже в бакете — валидируем и запускаем."""
    enforce_upload_limit(request)
    user = auth.require_user(request)
    _enforce_daily_quota(user)
    player_id = _validate_upload_meta(filename, player_id, training_platform)
    if not key.startswith(UPLOAD_PREFIX):
        raise HTTPException(status_code=400, detail="Некорректный ключ клипа")
    size = storage.video_size(key)
    if size is None:
        raise HTTPException(status_code=404,
                            detail="Клип не найден в хранилище — загрузка "
                                   "не дошла или истёк срок ссылки")
    if size > MAX_UPLOAD_BYTES:
        storage.delete_video(key)
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой: {size / 1048576:.0f} МБ "
                   f"при лимите {MAX_UPLOAD_MB:.0f} МБ. Обрежьте клип до "
                   f"нужного боя.")
    return await _create_and_enqueue(
        background_tasks, video_ref=key, filename=filename,
        player_id=player_id, sens=sens, edpi=edpi, agent=agent,
        map_name=map_name, training_platform=training_platform, user=user)


@app.post("/api/v1/analysis/upload")
async def upload_video(request: Request,
                       background_tasks: BackgroundTasks,
                       file: UploadFile = File(...),
                       player_id: str = Form(...),
                       sens: float | None = Form(None),
                       edpi: float | None = Form(None),
                       agent: str | None = Form(None),
                       map_name: str | None = Form(None),
                       training_platform: str | None = Form(None)):
    """Клип + player_id (людей не сливаем) + опциональный input-space."""
    enforce_upload_limit(request)
    user = auth.require_user(request)
    _enforce_daily_quota(user)
    player_id = _validate_upload_meta(file.filename, player_id,
                                     training_platform)
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой: {len(content) / 1048576:.0f} МБ "
                   f"при лимите {MAX_UPLOAD_MB:.0f} МБ. Обрежьте клип до "
                   f"нужного боя.")

    ext = os.path.splitext(file.filename or "")[1].lower()
    file_id = str(uuid.uuid4())
    video_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    with open(video_path, "wb") as buffer:
        buffer.write(content)

    # Мусор и оверлимит по длительности — 422 до создания сессии и до GPU.
    try:
        validate_clip(video_path)
    except ClipValidationError as exc:
        os.remove(video_path)
        raise HTTPException(status_code=422, detail=str(exc))

    return await _create_and_enqueue(
        background_tasks, video_ref=video_path, filename=file.filename,
        player_id=player_id, sens=sens, edpi=edpi, agent=agent,
        map_name=map_name, training_platform=training_platform, user=user)


@app.get("/healthz")
async def healthz():
    """Проверка живости для оркестратора и аптайм-мониторинга."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    body = {
        "status": "ok",
        "queue": os.getenv("QUEUE_BACKEND", "background"),
        "storage": os.getenv("STORAGE_BACKEND", "local"),
        "db": "ok",
    }
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:                              # noqa: BLE001 — статус в ответ
        logger.exception("healthz: БД недоступна")
        body.update(status="degraded", db="error")
        return JSONResponse(status_code=503, content=body)
    return body


@app.post("/api/v1/analysis/{session_id}/share")
async def share_analysis(session_id: str, request: Request):
    """Владелец получает стабильный share-токен для ссылки на отчёт."""
    import secrets as _secrets

    user = auth.current_user(request)
    try:
        session = db.get_session(uuid.UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Invalid session ID format")
    # 404 и для чужих: существование сессии не подтверждаем
    if (session is None or session.owner_user_id is None or user is None
            or session.owner_user_id != user.id):
        raise HTTPException(status_code=404,
                            detail="Analysis session not found")
    if not session.share_token:
        session = db.update_session(
            session.id, share_token=_secrets.token_urlsafe(16))
    return {"share_token": session.share_token}


@app.get("/api/v1/analysis/{session_id}")
async def get_analysis(session_id: str, request: Request,
                       share: str | None = None):
    """Статус пайплайна + полный результат, когда COMPLETED.

    Сессии с владельцем видит только владелец или гость с share-токеном;
    анонимные сессии (dev/легаси) остаются открытыми.
    """
    import secrets as _secrets

    try:
        session = db.get_session(uuid.UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Invalid session ID format")
    if not session:
        raise HTTPException(status_code=404,
                            detail="Analysis session not found")

    user = auth.current_user(request)
    is_owner = (session.owner_user_id is not None and user is not None
                and session.owner_user_id == user.id)
    if session.owner_user_id is not None and not is_owner:
        shared = (share is not None and session.share_token is not None
                  and _secrets.compare_digest(share, session.share_token))
        if not shared:
            raise HTTPException(status_code=404,
                                detail="Analysis session not found")

    def _loads(text):
        return json.loads(text) if text else None

    return {
        "is_owner": is_owner,
        "share_token": session.share_token if is_owner else None,
        "id": str(session.id),
        "status": session.status,
        "player_id": session.player_id,
        "clip_id": session.clip_id,
        "created_at": session.created_at,
        "evidence_report": _loads(session.evidence_report),
        "coach_report": _loads(session.coach_report),
        "coach_failed": session.coach_failed,
        "coach_errors": _loads(session.coach_errors) or [],
        # В БД лежат рефы (local: URL, r2: ключи) — наружу всегда URL.
        "evidence_frames": storage.resolve_evidence_urls(
            _loads(session.evidence_frames) or []),
        "error": session.error if session.status == "FAILED" else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
