# -*- coding: utf-8 -*-
"""Presigned-флоу загрузки (Этап 1): /uploads -> PUT в бакет -> /start.

R2 подменяется фейковым storage: проверяем контракт эндпоинтов —
режимы direct/presigned, валидацию ключа/размера, запуск сессии и
резолв рефов улик в URL при поллинге.
"""
import json
from typing import List, Optional

import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager


class FakeR2Storage:
    """Контракт services.storage.Storage без boto3/сети."""

    def __init__(self):
        self.objects = {}          # key -> size
        self.deleted = []
        self.blobs = {}            # key -> bytes (лог тренажёра в бакете)
        self.pipeline_stats = []   # что пайплайн прочитал по stats_path

    def presign_upload(self, filename: str) -> Optional[dict]:
        return {"upload_url": "https://r2.example/put/abc", "key": "uploads/abc.mp4"}

    def fetch_video(self, video_ref):
        import os
        import tempfile
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            if video_ref not in self.blobs:
                yield video_ref
                return
            fd, path = tempfile.mkstemp(suffix=os.path.splitext(video_ref)[1])
            with os.fdopen(fd, "wb") as f:
                f.write(self.blobs[video_ref])
            try:
                yield path
            finally:
                os.remove(path)
        return _cm()

    def publish_stats(self, local_path: str) -> str:
        import os
        from pathlib import Path
        key = f"uploads/{Path(local_path).name}"
        self.blobs[key] = Path(local_path).read_bytes()
        os.remove(local_path)
        return key

    def publish_evidence(self, session_id: str,
                         frame_paths: List[str]) -> List[str]:
        from pathlib import Path
        return [f"evidence/{session_id}/{Path(p).name}" for p in frame_paths]

    def resolve_evidence_urls(self, refs: List[str]) -> List[str]:
        return [f"https://r2.example/get/{r}" if not r.startswith("/") else r
                for r in refs]

    def video_size(self, key: str) -> Optional[int]:
        return self.objects.get(key)

    def delete_video(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.main as main

    db = DatabaseManager(f"sqlite:///{tmp_path / 'test.db'}")
    storage = FakeR2Storage()
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "storage", storage)
    monkeypatch.setattr(main, "EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))

    def fake_pipeline(video_path, player_id, *, evidence_dir, on_status=None,
                      stats_path=None, **kwargs):
        from pathlib import Path

        storage.pipeline_stats.append(
            Path(stats_path).read_bytes() if stats_path else None)
        from backend.services.analysis_pipeline import PipelineResult
        frame = Path(evidence_dir) / "frame_000042.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"jpg")
        return PipelineResult(
            evidence_report={"schema_version": "1.1"},
            evidence_frames=[str(frame)],
            coach_report=None, coach_failed=True,
            coach_errors=[], coach_attempts=1)

    monkeypatch.setattr(main, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(main, "validate_clip", lambda *a, **k: None)
    return TestClient(main.app), db, storage


def test_uploads_returns_presigned_mode(api):
    client, db, storage = api
    resp = client.post("/api/v1/analysis/uploads",
                       data={"filename": "clip3.mp4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "presigned"
    assert body["key"] == "uploads/abc.mp4"
    assert body["upload_url"].startswith("https://")


def test_uploads_rejects_bad_extension(api):
    client, *_ = api
    resp = client.post("/api/v1/analysis/uploads",
                       data={"filename": "notes.txt"})
    assert resp.status_code == 400


def test_start_runs_session_with_bucket_key(api):
    client, db, storage = api
    storage.objects["uploads/abc.mp4"] = 1000

    resp = client.post("/api/v1/analysis/start", data={
        "key": "uploads/abc.mp4", "filename": "clip3.mp4",
        "player_id": "friend"})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    got = client.get(f"/api/v1/analysis/{session_id}").json()
    assert got["status"] == "COMPLETED"
    assert got["clip_id"] == "clip3"          # stem исходного имени
    # рефы в БД — ключи бакета, наружу — URL
    assert got["evidence_frames"] == [
        f"https://r2.example/get/evidence/{session_id}/frame_000042.jpg"]
    row = db.get_session(__import__("uuid").UUID(session_id))
    assert json.loads(row.evidence_frames) == [
        f"evidence/{session_id}/frame_000042.jpg"]


def test_start_missing_object_is_404(api):
    client, *_ = api
    resp = client.post("/api/v1/analysis/start", data={
        "key": "uploads/nope.mp4", "filename": "clip3.mp4",
        "player_id": "friend"})
    assert resp.status_code == 404


def test_start_oversized_object_is_413_and_deleted(api, monkeypatch):
    client, db, storage = api
    import backend.main as main
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    storage.objects["uploads/abc.mp4"] = 100

    resp = client.post("/api/v1/analysis/start", data={
        "key": "uploads/abc.mp4", "filename": "clip3.mp4",
        "player_id": "friend"})
    assert resp.status_code == 413
    assert storage.deleted == ["uploads/abc.mp4"]


def test_start_rejects_foreign_key_prefix(api):
    # ключ вне uploads/ — попытка запустить разбор чужого объекта бакета
    client, db, storage = api
    storage.objects["evidence/sid/frame.jpg.mp4"] = 10
    resp = client.post("/api/v1/analysis/start", data={
        "key": "evidence/sid/frame.jpg.mp4", "filename": "clip3.mp4",
        "player_id": "friend"})
    assert resp.status_code == 400


def test_start_validates_platform_and_player(api):
    client, db, storage = api
    storage.objects["uploads/abc.mp4"] = 10
    assert client.post("/api/v1/analysis/start", data={
        "key": "uploads/abc.mp4", "filename": "clip3.mp4",
        "player_id": "friend", "training_platform": "csgo",
    }).status_code == 422
    assert client.post("/api/v1/analysis/start", data={
        "key": "uploads/abc.mp4", "filename": "clip3.mp4",
        "player_id": "   "}).status_code == 400


def test_uploads_direct_mode_with_local_storage(api, monkeypatch, tmp_path):
    client, db, _ = api
    import backend.main as main

    from backend.services.storage import LocalStorage
    monkeypatch.setattr(main, "storage", LocalStorage(str(tmp_path)))
    resp = client.post("/api/v1/analysis/uploads",
                       data={"filename": "clip3.mp4"})
    assert resp.json() == {"mode": "direct"}


# ------------------------------------------- лог тренажёра в presigned-пути

CSV = ("run Stats.csv", b"Kill #,Timestamp\n1,13:37:57.929\n", "text/csv")


def _start(client, *, stats=None, platform="kovaaks"):
    data = {"key": "uploads/abc.mp4", "filename": "clip3.mp4",
            "player_id": "friend"}
    if platform:
        data["training_platform"] = platform
    files = {"stats": stats} if stats else None
    return client.post("/api/v1/analysis/start", data=data, files=files)


def test_start_delivers_stats_to_pipeline_through_bucket(api):
    """Лог идёт в бакет, воркер скачивает его оттуда — не с диска API."""
    client, db, storage = api
    storage.objects["uploads/abc.mp4"] = 1000

    resp = _start(client, stats=CSV)

    assert resp.status_code == 200
    [key] = [k for k in storage.blobs if k.endswith("-stats.csv")]
    assert key.startswith("uploads/")
    assert storage.pipeline_stats == [CSV[1]]


def test_start_without_stats_passes_none(api):
    client, db, storage = api
    storage.objects["uploads/abc.mp4"] = 1000
    assert _start(client).status_code == 200
    assert storage.pipeline_stats == [None]


def test_start_rejects_stats_for_game_clip(api):
    client, db, storage = api
    storage.objects["uploads/abc.mp4"] = 1000
    resp = _start(client, stats=CSV, platform="ingame")
    assert resp.status_code == 422
    assert storage.blobs == {}
