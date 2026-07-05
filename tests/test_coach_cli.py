# -*- coding: utf-8 -*-
"""Тесты офлайн-CLI коуча (Stage B1): загрузка отчёта, сбор кадров, запись результата."""
import json
from pathlib import Path

from coach.schema import CoachReport
from coach_cli import collect_frames, main

FIXTURE = Path(__file__).resolve().parent.parent / "reports" / "friend_clip3.json"


class StubClient:
    def __init__(self):
        self.calls = []

    def generate(self, report, frame_paths):
        self.calls.append((report, list(frame_paths)))
        return CoachReport(
            summary="стаб-портрет",
            findings_explained=[],
            drills=[],
            caveats=["стаб"],
        )


def test_collect_frames_sorted_jpg_only(tmp_path: Path):
    d = tmp_path / "ev"
    d.mkdir()
    (d / "frame_000244.jpg").write_bytes(b"x")
    (d / "frame_000177.jpg").write_bytes(b"x")
    (d / "readme.txt").write_text("not a frame")
    frames = collect_frames(d)
    assert [p.name for p in frames] == ["frame_000177.jpg", "frame_000244.jpg"]


def test_main_writes_coach_report(tmp_path: Path):
    frames_dir = tmp_path / "ev"
    frames_dir.mkdir()
    (frames_dir / "frame_000177.jpg").write_bytes(b"\xff\xd8x")
    out = tmp_path / "coach.json"

    stub = StubClient()
    code = main(
        [str(FIXTURE), "--frames", str(frames_dir), "--out", str(out)],
        client=stub,
    )

    assert code == 0
    report_arg, frames_arg = stub.calls[0]
    assert report_arg["clip"]["player_id"] == "friend"
    assert [p.name for p in frames_arg] == ["frame_000177.jpg"]

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["summary"] == "стаб-портрет"
    assert written["caveats"] == ["стаб"]


def test_main_works_without_frames_dir(tmp_path: Path):
    out = tmp_path / "coach.json"
    stub = StubClient()
    code = main([str(FIXTURE), "--out", str(out)], client=stub)
    assert code == 0
    _, frames_arg = stub.calls[0]
    assert frames_arg == []


class AlwaysInvalidStub:
    """Клиент, который всегда выдумывает кадр — валидация должна провалиться."""

    def __init__(self):
        self.calls = 0

    def generate(self, report, frame_paths, feedback=None):
        self.calls += 1
        return CoachReport(
            summary="выдумка",
            findings_explained=[
                {
                    "metric": "consistency",
                    "explanation": "Кадр из воздуха.",
                    "evidence_frames": [999999],
                    "confidence": "diagnosis",
                }
            ],
            drills=[],
            caveats=[],
        )


def test_main_coach_failed_returns_error_and_writes_nothing(tmp_path: Path, capsys):
    out = tmp_path / "coach.json"
    stub = AlwaysInvalidStub()
    code = main([str(FIXTURE), "--out", str(out)], client=stub)
    assert code == 1
    assert stub.calls == 2  # первый вызов + один ретрай
    assert not out.exists()
    captured = capsys.readouterr()
    assert "999999" in captured.err
