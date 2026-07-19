# -*- coding: utf-8 -*-
"""Этап 2: мусор отклоняется ДО GPU, длина клипа ограничена (цена разбора).

Кэп длительности — из юнит-экономики (docs/UNIT_ECONOMICS.md): цена
растёт линейно от длительности, мегабайтный лимит её не ограничивает.
"""
import numpy as np
import pytest

from backend.services.clip_validation import (ClipValidationError,
                                              validate_clip)


@pytest.fixture(scope="module")
def real_clip(tmp_path_factory):
    """Настоящий mp4: 2 секунды, 32x24, 10 fps."""
    import cv2

    path = str(tmp_path_factory.mktemp("clips") / "tiny.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"),
                             10, (32, 24))
    for i in range(20):
        writer.write(np.full((24, 32, 3), i * 10 % 255, dtype=np.uint8))
    writer.release()
    return path


def test_valid_clip_passes_and_reports_duration(real_clip):
    info = validate_clip(real_clip, max_seconds=120)
    assert info.duration_s == pytest.approx(2.0, abs=0.3)
    assert info.width == 32 and info.height == 24


def test_garbage_bytes_rejected(tmp_path):
    bad = tmp_path / "garbage.mp4"
    bad.write_bytes(b"\x00definitely-not-a-video" * 100)
    with pytest.raises(ClipValidationError, match="не удалось прочитать"):
        validate_clip(str(bad), max_seconds=120)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ClipValidationError):
        validate_clip(str(tmp_path / "nope.mp4"), max_seconds=120)


def test_too_long_clip_rejected_with_limit_in_message(real_clip):
    with pytest.raises(ClipValidationError, match="1 сек"):
        validate_clip(real_clip, max_seconds=1)


def test_upload_endpoint_rejects_garbage_as_422(tmp_path, monkeypatch):
    """Прямой аплоад: мусорный файл — 422 до создания сессии."""
    from fastapi.testclient import TestClient

    import backend.main as main
    from backend.database import DatabaseManager

    db = DatabaseManager(f"sqlite:///{tmp_path / 'v.db'}")
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))
    client = TestClient(main.app)

    resp = client.post(
        "/api/v1/analysis/upload",
        files={"file": ("clip.mp4", b"\x00not-a-video", "video/mp4")},
        data={"player_id": "p"})
    assert resp.status_code == 422
    assert "видео" in resp.json()["detail"].lower()
    # файл-мусор не остался на диске
    assert not list(tmp_path.glob("*.mp4"))


def test_worker_path_fails_session_with_human_message(tmp_path, real_clip):
    """R2-путь: валидация в задаче — FAILED с понятной ошибкой, без пайплайна."""
    from backend.database import DatabaseManager
    from backend.services.analysis_task import (AnalysisJob,
                                                run_analysis_session)
    from backend.services.clip_validation import validate_clip as validator

    db = DatabaseManager(f"sqlite:///{tmp_path / 'w.db'}")
    session = db.create_session(real_clip, player_id="p", clip_id="c")
    called = []

    def pipeline(*a, **k):
        called.append(1)

    run_analysis_session(
        db, AnalysisJob(session_id=str(session.id), video_path=real_clip,
                        player_id="p", clip_id="c"),
        evidence_dir=str(tmp_path), pipeline=pipeline,
        validator=lambda path: validator(path, max_seconds=1))

    row = db.get_session(session.id)
    assert row.status == "FAILED"
    assert "1 сек" in row.error
    assert called == []                   # GPU-пайплайн не запускался
