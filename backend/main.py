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
                     UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import DatabaseManager
from backend.services.analysis_pipeline import run_pipeline
from backend.services.history_provider import make_history_provider

load_dotenv()
logger = logging.getLogger(__name__)

app = FastAPI(title="Valorant AI Aim Coach", version="2.0.0")

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

ALLOWED_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv")
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "300"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)


async def process_video_task(session_id: str, video_path: str,
                             player_id: str, clip_id: str,
                             sens: float | None, edpi: float | None,
                             agent: str | None, map_name: str | None,
                             training_platform: str | None) -> None:
    """Фон: пайплайн двигает статус сессии, итог пишется JSON-колонками."""
    sid = uuid.UUID(session_id)

    def on_status(status: str) -> None:
        db.update_session(sid, status=status)

    try:
        loop = asyncio.get_event_loop()
        session_evidence_dir = os.path.join(EVIDENCE_DIR, session_id)
        result = await loop.run_in_executor(None, lambda: run_pipeline(
            video_path, player_id, clip_id=clip_id, sens=sens, edpi=edpi,
            agent=agent, map_name=map_name, training_platform=training_platform,
            evidence_dir=session_evidence_dir, on_status=on_status,
            history_provider=make_history_provider(db)))

        frame_urls = [f"/evidence/{session_id}/{Path(p).name}"
                      for p in result.evidence_frames]
        db.update_session(
            sid,
            status="COMPLETED",
            evidence_report=json.dumps(result.evidence_report,
                                       ensure_ascii=False),
            coach_report=(json.dumps(result.coach_report, ensure_ascii=False)
                          if result.coach_report is not None else None),
            coach_failed=result.coach_failed,
            coach_errors=json.dumps(result.coach_errors, ensure_ascii=False),
            evidence_frames=json.dumps(frame_urls),
        )
    except Exception as exc:                       # noqa: BLE001 — в БД и лог
        logger.exception("пайплайн упал: session %s", session_id)
        db.update_session(sid, status="FAILED", error=str(exc))


@app.post("/api/v1/analysis/upload")
async def upload_video(background_tasks: BackgroundTasks,
                       file: UploadFile = File(...),
                       player_id: str = Form(...),
                       sens: float | None = Form(None),
                       edpi: float | None = Form(None),
                       agent: str | None = Form(None),
                       map_name: str | None = Form(None),
                       training_platform: str | None = Form(None)):
    """Клип + player_id (людей не сливаем) + опциональный input-space."""
    ext = os.path.splitext(file.filename or "")[1].lower()
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

    # clip_id = stem исходного имени: повторная загрузка того же клипа
    # идемпотентно перезаписывает его в продольном профиле.
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой: {len(content) / 1048576:.0f} МБ "
                   f"при лимите {MAX_UPLOAD_MB:.0f} МБ. Обрежьте клип до "
                   f"нужного боя.")

    clip_id = Path(file.filename).stem
    file_id = str(uuid.uuid4())
    video_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    with open(video_path, "wb") as buffer:
        buffer.write(content)

    session = db.create_session(video_path, player_id=player_id,
                                clip_id=clip_id)
    background_tasks.add_task(process_video_task, str(session.id), video_path,
                              player_id, clip_id, sens, edpi, agent, map_name,
                              training_platform)
    return {
        "session_id": str(session.id),
        "status": session.status,
        "message": "Клип загружен, анализ запущен.",
    }


@app.get("/api/v1/analysis/{session_id}")
async def get_analysis(session_id: str):
    """Статус пайплайна + полный результат, когда COMPLETED."""
    try:
        session = db.get_session(uuid.UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Invalid session ID format")
    if not session:
        raise HTTPException(status_code=404,
                            detail="Analysis session not found")

    def _loads(text):
        return json.loads(text) if text else None

    return {
        "id": str(session.id),
        "status": session.status,
        "player_id": session.player_id,
        "clip_id": session.clip_id,
        "created_at": session.created_at,
        "evidence_report": _loads(session.evidence_report),
        "coach_report": _loads(session.coach_report),
        "coach_failed": session.coach_failed,
        "coach_errors": _loads(session.coach_errors) or [],
        "evidence_frames": _loads(session.evidence_frames) or [],
        "error": session.error if session.status == "FAILED" else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
