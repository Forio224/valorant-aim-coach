# -*- coding: utf-8 -*-
"""Очередь разборов (Этап 1 запуска): background (dev) | arq (прод).

background — прежнее поведение: задача живёт в процессе API и умирает
вместе с ним (для локальной разработки и тестов этого достаточно).
arq — джоба в Redis: переживает рестарт API, исполняется воркером
(backend/worker.py), _job_id = session_id даёт дедупликацию повторов.
"""
import os
from typing import Awaitable, Callable, Optional, Protocol

from backend.services.analysis_task import AnalysisJob

__all__ = ["AnalysisJob", "JobQueue", "BackgroundJobQueue", "ArqJobQueue",
           "create_job_queue"]

ANALYZE_TASK_NAME = "analyze_clip"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class JobQueue(Protocol):
    async def enqueue(self, background_tasks, job: AnalysisJob) -> None:
        """Поставить разбор в очередь; background_tasks нужен только
        background-бэкенду (FastAPI BackgroundTasks текущего запроса)."""


class BackgroundJobQueue:
    """In-process исполнение через FastAPI BackgroundTasks (как раньше)."""

    def __init__(self, runner: Callable[[AnalysisJob], Awaitable[None]]):
        self._runner = runner

    async def enqueue(self, background_tasks, job: AnalysisJob) -> None:
        background_tasks.add_task(self._runner, job)


class ArqJobQueue:
    """Постановка джобы в Redis; пул создаётся лениво при первом enqueue."""

    def __init__(self, redis_url: str, pool=None):
        self.redis_url = redis_url
        self._pool = pool

    async def _get_pool(self):
        if self._pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings

            self._pool = await create_pool(
                RedisSettings.from_dsn(self.redis_url))
        return self._pool

    async def enqueue(self, background_tasks, job: AnalysisJob) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(ANALYZE_TASK_NAME, job.to_payload(),
                               _job_id=job.session_id)


def create_job_queue(
        runner: Optional[Callable[[AnalysisJob], Awaitable[None]]] = None):
    """Собрать очередь по QUEUE_BACKEND (background — дефолт | arq).

    Опечатка в конфиге — ошибка на старте, а не молчаливый откат в
    background-режим (на проде это значило бы «очереди нет»).
    """
    backend = os.getenv("QUEUE_BACKEND", "background").strip().lower()
    if backend == "background":
        async def _noop(job: AnalysisJob) -> None:   # для тестов без раннера
            raise RuntimeError("BackgroundJobQueue без раннера")

        return BackgroundJobQueue(runner or _noop)
    if backend == "arq":
        return ArqJobQueue(os.getenv("REDIS_URL", DEFAULT_REDIS_URL))
    raise ValueError(
        f"QUEUE_BACKEND={backend!r}: ожидается 'background' или 'arq'")
