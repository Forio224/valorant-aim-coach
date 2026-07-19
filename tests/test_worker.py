# -*- coding: utf-8 -*-
"""arq-воркер: analyze_clip исполняет пайплайн и двигает сессию в БД.

Redis и YOLO не нужны: db/pipeline инжектируются через ctx — тот же принцип
инъекции, что в analysis_pipeline (детектор и коуч подменяемы).
"""
import asyncio
import json
from pathlib import Path

from backend.database import DatabaseManager
from backend.services.analysis_pipeline import PipelineResult
from backend.worker import analyze_clip


def _payload(session, video_path="v.mp4"):
    return {
        "session_id": str(session.id),
        "video_path": video_path,
        "player_id": "friend",
        "clip_id": "clip3",
        "sens": 0.4,
        "edpi": None,
        "agent": None,
        "map_name": None,
        "training_platform": None,
    }


def _ctx(tmp_path, db, pipeline):
    return {
        "db": db,
        "evidence_dir": str(tmp_path / "evidence"),
        "pipeline": pipeline,
        "history_provider": None,
    }


def _result(frames):
    return PipelineResult(
        evidence_report={"schema_version": "1.1"},
        evidence_frames=frames,
        coach_report={"summary": "Портрет.", "findings_explained": [],
                      "drills": [], "caveats": []},
        coach_failed=False,
        coach_errors=[],
        coach_attempts=1,
    )


def test_analyze_clip_completes_session(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'w.db'}")
    session = db.create_session("v.mp4", player_id="friend", clip_id="clip3")
    statuses = []

    def pipeline(video_path, player_id, *, on_status=None, evidence_dir,
                 **kwargs):
        if on_status:
            on_status("DETECTING")
        statuses.append(db.get_session(session.id).status)
        frame = Path(evidence_dir) / "frame_000001.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"jpg")
        return _result([str(frame)])

    asyncio.run(analyze_clip(_ctx(tmp_path, db, pipeline), _payload(session)))

    row = db.get_session(session.id)
    assert statuses == ["DETECTING"]          # on_status дошёл до БД
    assert row.status == "COMPLETED"
    assert json.loads(row.evidence_frames) == [
        f"/evidence/{session.id}/frame_000001.jpg"]
    assert json.loads(row.coach_report)["summary"] == "Портрет."


def test_analyze_clip_marks_failed_on_pipeline_error(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'w.db'}")
    session = db.create_session("v.mp4", player_id="friend", clip_id="clip3")

    def broken(*args, **kwargs):
        raise RuntimeError("видео битое")

    asyncio.run(analyze_clip(_ctx(tmp_path, db, broken), _payload(session)))

    row = db.get_session(session.id)
    assert row.status == "FAILED"
    assert "видео битое" in row.error
