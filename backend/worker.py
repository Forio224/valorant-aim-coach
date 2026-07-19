# -*- coding: utf-8 -*-
"""arq-воркер разборов (Этап 1 запуска).

Запуск (нужен Redis, см. REDIS_URL):
    .\\.venv\\Scripts\\python.exe -m arq backend.worker.WorkerSettings

Джоба переживает рестарт API (лежит в Redis) и падение воркера
(перепоставка по истечении job_timeout). Повторный прогон безопасен:
профиль идемпотентен по clip_id, кадры-улики перезаписываются.
Детерминированная ошибка пайплайна -> FAILED в БД без ретрая arq
(run_analysis_session не пробрасывает исключение).
"""
import asyncio
import logging
import os
from functools import partial

from arq.connections import RedisSettings
from dotenv import load_dotenv

from backend.services.analysis_task import AnalysisJob, run_analysis_session

load_dotenv()   # REDIS_URL нужен уже на импорте (класс-атрибут WorkerSettings)
logger = logging.getLogger(__name__)

JOB_TIMEOUT_S = 30 * 60        # потолок разбора; дольше — считаем зависшим
MAX_TRIES = 3                  # перепоставки после падений воркера
KEEP_RESULT_S = 24 * 3600


async def analyze_clip(ctx: dict, payload: dict) -> None:
    """Разбор одной сессии; тяжёлый sync-пайплайн — в executor."""
    job = AnalysisJob.from_payload(payload)
    logger.info("analyze_clip: session %s clip %s", job.session_id,
                job.clip_id)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(
        run_analysis_session, ctx["db"], job,
        evidence_dir=ctx["evidence_dir"],
        pipeline=ctx["pipeline"],
        history_provider=ctx["history_provider"],
        storage=ctx.get("storage")))


async def startup(ctx: dict) -> None:
    """Свой DatabaseManager и реальный пайплайн — раз на процесс воркера."""
    from backend.database import DatabaseManager
    from backend.services.analysis_pipeline import run_pipeline
    from backend.services.history_provider import make_history_provider

    db = DatabaseManager(os.getenv("DATABASE_URL", "sqlite:///./aim_coach.db"))
    upload_dir = os.getenv("UPLOAD_DIR", "uploads")
    ctx["db"] = db
    ctx["evidence_dir"] = os.getenv("EVIDENCE_DIR",
                                    os.path.join(upload_dir, "evidence"))
    ctx["pipeline"] = run_pipeline
    ctx["history_provider"] = make_history_provider(db)
    from backend.services.storage import create_storage

    ctx["storage"] = create_storage(evidence_dir=ctx["evidence_dir"])


class WorkerSettings:
    functions = [analyze_clip]
    on_startup = startup
    job_timeout = JOB_TIMEOUT_S
    max_tries = MAX_TRIES
    keep_result = KEEP_RESULT_S
    max_jobs = int(os.getenv("WORKER_MAX_JOBS", "1"))  # GPU — один разбор за раз
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"))
