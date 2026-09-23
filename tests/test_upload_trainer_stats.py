# -*- coding: utf-8 -*-
"""Приём файла статистики тренажёра на границе API.

Лог — второй, необязательный файл формы. Правила простые и все проверяются
здесь: без лога всё работает как раньше; лог принимается только для
платформ-тренажёров; расширение валидируется до создания сессии; путь
доезжает до пайплайна через задачу.
"""
import uuid
from pathlib import Path
from typing import List, Optional

import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager
from backend.services.analysis_pipeline import PipelineResult

MP4 = ("clip3.mp4", b"\x00fake-mp4-bytes", "video/mp4")
CSV = ("run Stats.csv", b"Kill #,Timestamp\n1,13:37:57.929\n", "text/csv")


def _result() -> PipelineResult:
    return PipelineResult(
        evidence_report={"schema_version": "1.5",
                         "clip": {"player_id": "friend", "clip_id": "clip3"},
                         "episodes": [], "findings": []},
        evidence_frames=[], coach_report={"summary": "Портрет.",
                                          "findings_explained": [],
                                          "drills": [], "caveats": []},
        coach_failed=False, coach_errors=[], coach_attempts=1)


@pytest.fixture
def api(tmp_path, monkeypatch):
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
                      edpi=None, agent=None, map_name=None,
                      training_platform=None, config=None,
                      evidence_dir, on_status=None, detector=None,
                      coach_client=None, history_provider=None,
                      steam_id=None, external_fetcher=None, stats_path=None):
        calls.append(dict(video_path=video_path,
                          training_platform=training_platform,
                          stats_path=stats_path))
        return _result()

    monkeypatch.setattr(main, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(main, "validate_clip", lambda *a, **k: None)
    return TestClient(main.app), db, calls


def _upload(client, data=None, files=None):
    payload = {"player_id": "friend"} if data is None else data
    return client.post("/api/v1/analysis/upload",
                       files=files or {"file": MP4}, data=payload)


# ---------------------------------------------------------------- happy path

def test_stats_file_reaches_the_pipeline(api):
    client, db, calls = api
    resp = _upload(client,
                   data={"player_id": "friend",
                         "training_platform": "kovaaks"},
                   files={"file": MP4, "stats": CSV})
    assert resp.status_code == 200
    assert calls[0]["stats_path"] is not None
    assert Path(calls[0]["stats_path"]).exists()


def test_stats_file_content_is_saved_verbatim(api):
    client, db, calls = api
    _upload(client, data={"player_id": "friend",
                          "training_platform": "kovaaks"},
            files={"file": MP4, "stats": CSV})
    saved = Path(calls[0]["stats_path"]).read_bytes()
    assert saved == CSV[1]


def test_upload_without_stats_still_works(api):
    """Лог необязателен — прежний сценарий не должен измениться."""
    client, db, calls = api
    resp = _upload(client, data={"player_id": "friend",
                                 "training_platform": "kovaaks"})
    assert resp.status_code == 200
    assert calls[0]["stats_path"] is None


def test_aimbeast_json_export_accepted(api):
    client, db, calls = api
    resp = _upload(client,
                   data={"player_id": "friend",
                         "training_platform": "aimbeast"},
                   files={"file": MP4,
                          "stats": ("run.json", b"{}", "application/json")})
    assert resp.status_code == 200
    assert calls[0]["stats_path"] is not None


# ----------------------------------------------------------------- валидация

def test_stats_rejected_for_game_clip(api):
    """У игрового клипа выстрелы ничем не измеряются — лог там бессмыслен."""
    client, db, calls = api
    resp = _upload(client,
                   data={"player_id": "friend", "training_platform": "ingame"},
                   files={"file": MP4, "stats": CSV})
    assert resp.status_code == 422
    assert calls == []


def test_stats_with_bad_extension_is_rejected(api):
    client, db, calls = api
    resp = _upload(client,
                   data={"player_id": "friend",
                         "training_platform": "kovaaks"},
                   files={"file": MP4,
                          "stats": ("log.exe", b"MZ", "application/exe")})
    assert resp.status_code == 422
    assert calls == []


def test_oversized_stats_is_rejected(api, monkeypatch):
    import backend.main as main
    monkeypatch.setattr(main, "MAX_STATS_BYTES", 4)
    client, db, calls = api
    resp = _upload(client,
                   data={"player_id": "friend",
                         "training_platform": "kovaaks"},
                   files={"file": MP4, "stats": CSV})
    assert resp.status_code == 413
    assert calls == []
