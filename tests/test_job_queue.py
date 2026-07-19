# -*- coding: utf-8 -*-
"""Этап 1 запуска: очередь задач вместо голых BackgroundTasks.

Контракт: QUEUE_BACKEND=background (дефолт, dev/тесты без Redis) сохраняет
текущее поведение; QUEUE_BACKEND=arq кладёт джобу в Redis (пайплайн
переживает рестарт API), _job_id = session_id — дедупликация повторов.
Сам Redis в тестах не нужен: пул подменяется фейком.
"""
import asyncio
import uuid

import pytest

from backend.services.job_queue import (AnalysisJob, ArqJobQueue,
                                        BackgroundJobQueue, create_job_queue)


def _job(**overrides) -> AnalysisJob:
    base = dict(
        session_id=str(uuid.uuid4()),
        video_path="uploads/x.mp4",
        player_id="friend",
        clip_id="clip3",
        sens=0.4,
        edpi=320.0,
        agent="Jett",
        map_name="Ascent",
        training_platform=None,
    )
    base.update(overrides)
    return AnalysisJob(**base)


# ------------------------------------------------------------ выбор бэкенда

def test_default_backend_is_background(monkeypatch):
    monkeypatch.delenv("QUEUE_BACKEND", raising=False)
    assert isinstance(create_job_queue(), BackgroundJobQueue)


def test_arq_backend_selected_from_env(monkeypatch):
    monkeypatch.setenv("QUEUE_BACKEND", "arq")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/3")
    queue = create_job_queue()
    assert isinstance(queue, ArqJobQueue)
    assert queue.redis_url == "redis://localhost:6379/3"


def test_unknown_backend_fails_fast(monkeypatch):
    # Опечатка в конфиге не должна молча превращаться в background-режим:
    # на проде это означало бы «очереди нет, рестарт убивает разборы».
    monkeypatch.setenv("QUEUE_BACKEND", "celery")
    with pytest.raises(ValueError, match="QUEUE_BACKEND"):
        create_job_queue()


# ------------------------------------------------------------------- arq

class FakePool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, payload, _job_id=None):
        self.jobs.append((name, payload, _job_id))
        return object()


def test_arq_enqueue_sends_payload_with_session_job_id():
    pool = FakePool()
    queue = ArqJobQueue("redis://ignored", pool=pool)
    job = _job()

    asyncio.run(queue.enqueue(None, job))

    (name, payload, job_id), = pool.jobs
    assert name == "analyze_clip"
    assert job_id == job.session_id           # дедуп по сессии
    assert payload["video_path"] == "uploads/x.mp4"
    assert payload["sens"] == pytest.approx(0.4)
    assert payload["training_platform"] is None


# ------------------------------------------------------- background-режим

class FakeBackgroundTasks:
    def __init__(self):
        self.added = []

    def add_task(self, fn, *args, **kwargs):
        self.added.append((fn, args, kwargs))


def test_background_enqueue_delegates_to_fastapi_background_tasks():
    runs = []

    async def runner(job):
        runs.append(job)

    queue = BackgroundJobQueue(runner)
    tasks = FakeBackgroundTasks()
    job = _job()

    asyncio.run(queue.enqueue(tasks, job))

    (fn, args, _), = tasks.added
    assert fn is runner
    assert args == (job,)
