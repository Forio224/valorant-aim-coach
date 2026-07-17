# -*- coding: utf-8 -*-
"""Stage B3: API поверх пайплайна (upload/poll) + новая схема БД.

Пайплайн подменяется фейком (реальный YOLO/коуч не трогаем): проверяем
контракт эндпоинтов, прокидку метаданных, статусы, деградацию coach_failed
и URL кадров-улик. TestClient гоняет BackgroundTasks синхронно.
"""
import json
import os
import uuid
from pathlib import Path
from typing import List, Optional

import pytest
from fastapi.testclient import TestClient

from backend.database import AnalysisSession, DatabaseManager
from backend.services.analysis_pipeline import PipelineResult

MP4 = ("clip3.mp4", b"\x00fake-mp4-bytes", "video/mp4")


def _result(coach_failed: bool = False,
            frames: Optional[List[str]] = None) -> PipelineResult:
    return PipelineResult(
        evidence_report={"schema_version": "1.1",
                         "clip": {"player_id": "friend", "clip_id": "clip3"},
                         "episodes": [], "findings": []},
        evidence_frames=frames if frames is not None else [],
        coach_report=None if coach_failed else {"summary": "Портрет.",
                                                "findings_explained": [],
                                                "drills": [], "caveats": []},
        coach_failed=coach_failed,
        coach_errors=["число 9.99 не из движка"] if coach_failed else [],
        coach_attempts=2 if coach_failed else 1,
    )


@pytest.fixture
def api(tmp_path, monkeypatch):
    """TestClient с изолированной БД/каталогами и фейковым пайплайном."""
    import backend.main as main

    db = DatabaseManager(f"sqlite:///{tmp_path / 'test.db'}")
    upload_dir = tmp_path / "uploads"
    evidence_dir = tmp_path / "evidence"
    upload_dir.mkdir()
    evidence_dir.mkdir()
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(main, "EVIDENCE_DIR", str(evidence_dir))

    calls: List[dict] = []

    def fake_pipeline(video_path, player_id, *, clip_id=None, sens=None,
                      edpi=None, agent=None, map_name=None, config=None,
                      evidence_dir, on_status=None, detector=None,
                      coach_client=None, history_provider=None):
        calls.append(dict(video_path=video_path, player_id=player_id,
                          clip_id=clip_id, sens=sens, edpi=edpi, agent=agent,
                          map_name=map_name, evidence_dir=evidence_dir))
        if on_status is not None:
            on_status("DETECTING")
            with_session = db_status_now(db)
            calls[-1]["db_status_after_on_status"] = with_session
        frame = Path(evidence_dir) / "frame_000177.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"jpg")
        return _result(frames=[str(frame)])

    monkeypatch.setattr(main, "run_pipeline", fake_pipeline)
    return TestClient(main.app), db, main, calls


def db_status_now(db: DatabaseManager) -> str:
    """Статус единственной сессии в тестовой БД."""
    from sqlmodel import Session, select
    with Session(db.engine) as session:
        return session.exec(select(AnalysisSession)).one().status


def _upload(client, data=None, file=MP4):
    payload = {"player_id": "friend"} if data is None else data
    return client.post("/api/v1/analysis/upload",
                       files={"file": file}, data=payload)


# ---------------------------------------------------------------- валидация

def test_upload_requires_player_id(api):
    client, *_ = api
    resp = client.post("/api/v1/analysis/upload", files={"file": MP4})
    assert resp.status_code == 422


def test_upload_rejects_non_video(api):
    client, *_ = api
    resp = _upload(client, file=("notes.txt", b"text", "text/plain"))
    assert resp.status_code == 400


def test_upload_larger_than_limit_is_413(api, monkeypatch):
    client, *_ = api
    import backend.main as main
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 4)   # MP4-фикстура больше
    resp = _upload(client)
    assert resp.status_code == 413
    assert "вели" in resp.json()["detail"].lower() or \
           "больш" in resp.json()["detail"].lower()


# ------------------------------------------------------------ happy path

def test_upload_then_poll_returns_coach_report(api):
    client, db, main, calls = api
    resp = _upload(client)
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    got = client.get(f"/api/v1/analysis/{session_id}").json()
    assert got["status"] == "COMPLETED"
    assert got["player_id"] == "friend"
    assert got["evidence_report"]["schema_version"] == "1.1"
    assert got["coach_report"]["summary"] == "Портрет."
    assert got["coach_failed"] is False
    assert got["error"] is None


def test_upload_passes_metadata_and_clip_id_to_pipeline(api):
    client, db, main, calls = api
    _upload(client, data={"player_id": "friend", "sens": "0.4",
                          "edpi": "320", "agent": "Jett",
                          "map_name": "Ascent"})
    call = calls[0]
    assert call["player_id"] == "friend"
    assert call["clip_id"] == "clip3"          # stem исходного имени файла
    assert call["sens"] == pytest.approx(0.4)
    assert call["edpi"] == pytest.approx(320.0)
    assert call["agent"] == "Jett"
    assert call["map_name"] == "Ascent"


def test_on_status_writes_pipeline_status_to_db(api):
    client, db, main, calls = api
    _upload(client)
    assert calls[0]["db_status_after_on_status"] == "DETECTING"


def test_evidence_frames_exposed_as_urls(api):
    client, db, main, calls = api
    session_id = _upload(client).json()["session_id"]
    got = client.get(f"/api/v1/analysis/{session_id}").json()
    assert got["evidence_frames"] == [
        f"/evidence/{session_id}/frame_000177.jpg"]


def test_pipeline_gets_per_session_evidence_dir(api):
    client, db, main, calls = api
    session_id = _upload(client).json()["session_id"]
    assert Path(calls[0]["evidence_dir"]).name == session_id


# ------------------------------------------------------------- деградация

def test_coach_failed_still_completes_with_partial_result(api):
    client, db, main, calls = api
    monkey_result = _result(coach_failed=True)

    def failing_coach_pipeline(video_path, player_id, **kwargs):
        return monkey_result

    import backend.main as main_mod
    main_mod_run = main_mod.run_pipeline
    try:
        main_mod.run_pipeline = failing_coach_pipeline
        session_id = _upload(client).json()["session_id"]
    finally:
        main_mod.run_pipeline = main_mod_run

    got = client.get(f"/api/v1/analysis/{session_id}").json()
    assert got["status"] == "COMPLETED"
    assert got["coach_failed"] is True
    assert got["coach_report"] is None
    assert got["coach_errors"] == ["число 9.99 не из движка"]
    assert got["evidence_report"] is not None


def test_pipeline_exception_marks_session_failed(api):
    client, db, main, calls = api

    def broken_pipeline(*args, **kwargs):
        raise RuntimeError("видео битое")

    import backend.main as main_mod
    saved = main_mod.run_pipeline
    try:
        main_mod.run_pipeline = broken_pipeline
        session_id = _upload(client).json()["session_id"]
    finally:
        main_mod.run_pipeline = saved

    got = client.get(f"/api/v1/analysis/{session_id}").json()
    assert got["status"] == "FAILED"
    assert "видео битое" in got["error"]


# ----------------------------------------------------------------- lookup

def test_get_unknown_session_is_404(api):
    client, *_ = api
    assert client.get(f"/api/v1/analysis/{uuid.uuid4()}").status_code == 404


def test_get_malformed_session_id_is_400(api):
    client, *_ = api
    assert client.get("/api/v1/analysis/not-a-uuid").status_code == 400


# --------------------------------------------------------------------- БД

def test_db_session_stores_new_columns(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'db.sqlite'}")
    created = db.create_session("v.mp4", player_id="p1", clip_id="c1")
    assert created.status == "PENDING"
    updated = db.update_session(created.id, status="COMPLETED",
                                coach_failed=True,
                                evidence_report='{"a": 1}')
    assert updated.coach_failed is True
    assert db.get_session(created.id).evidence_report == '{"a": 1}'
