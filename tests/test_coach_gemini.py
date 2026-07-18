# -*- coding: utf-8 -*-
"""Тесты GeminiCoachClient: сборка input, кап картинок, structured output, ключ."""
import base64
import json
from pathlib import Path

import pytest

from coach.providers.gemini import DEFAULT_MODEL, GeminiCoachClient
from coach.schema import CoachReport

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "friend_clip3.json"
FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


@pytest.fixture
def report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def frames_dir(tmp_path: Path) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    for n in [177, 244, 251, 276, 371, 394, 479, 487, 507, 179, 600, 601]:
        (d / f"frame_{n:06d}.jpg").write_bytes(FAKE_JPEG)
    return d


def _client() -> GeminiCoachClient:
    return GeminiCoachClient(api_key="test-key")


def test_default_model():
    # gemini-2.5-flash закрыт для новых аккаунтов (404) — дефолт 3.5
    assert DEFAULT_MODEL == "gemini-3.5-flash"
    assert _client().model == "gemini-3.5-flash"


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("COACH_MODEL", "gemini-3.1-flash-lite")
    assert GeminiCoachClient(api_key="test-key").model == "gemini-3.1-flash-lite"


def test_explicit_model_beats_env(monkeypatch):
    monkeypatch.setenv("COACH_MODEL", "gemini-3.1-flash-lite")
    c = GeminiCoachClient(api_key="test-key", model="gemini-3.5-flash")
    assert c.model == "gemini-3.5-flash"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiCoachClient()


def test_build_input_starts_with_system_then_report(report, frames_dir):
    parts = _client().build_input(report, sorted(frames_dir.glob("*.jpg")))
    # первый блок — системный промпт, второй — текст с JSON
    assert parts[0]["type"] == "text"
    assert "тренер по аиму" in parts[0]["text"].lower() or "Valorant" in parts[0]["text"]
    assert parts[1]["type"] == "text"
    assert '"player_id": "friend"' in parts[1]["text"]


def test_build_input_caps_images(report, frames_dir):
    paths = sorted(frames_dir.glob("*.jpg"))
    assert len(paths) == 12
    parts = _client().build_input(report, paths)
    images = [p for p in parts if p["type"] == "image"]
    assert len(images) == 10


def test_image_parts_are_base64_jpeg_with_labels(report, frames_dir):
    paths = [frames_dir / "frame_000177.jpg"]
    parts = _client().build_input(report, paths)
    images = [p for p in parts if p["type"] == "image"]
    assert len(images) == 1
    assert images[0]["mime_type"] == "image/jpeg"
    assert base64.b64decode(images[0]["data"]) == FAKE_JPEG
    idx = parts.index(images[0])
    assert parts[idx - 1]["type"] == "text"
    assert "177" in parts[idx - 1]["text"]


def test_build_input_appends_feedback(report, frames_dir):
    parts = _client().build_input(
        report, sorted(frames_dir.glob("*.jpg")), feedback="кадр 999 не существует"
    )
    assert parts[-1]["type"] == "text"
    assert "кадр 999 не существует" in parts[-1]["text"]


def test_generate_parses_structured_output(report, frames_dir, monkeypatch):
    coach_report = CoachReport(summary="ок", findings_explained=[], drills=[], caveats=[])
    captured: dict = {}

    class StubInteractions:
        # публичный стиль SDK: create(model=..., input=[...], response_format=...)
        def create(self, **kwargs):
            captured.update(kwargs)

            class Resp:
                output_text = coach_report.model_dump_json()
                usage = None

            return Resp()

    class StubGenaiClient:
        interactions = StubInteractions()

    c = _client()
    monkeypatch.setattr(c, "_client", StubGenaiClient())
    result = c.generate(report, sorted(frames_dir.glob("*.jpg")))

    assert isinstance(result, CoachReport)
    assert result.summary == "ок"
    assert captured["model"] == "gemini-3.5-flash"
    assert isinstance(captured["input"], list)
    assert any(p["type"] == "image" for p in captured["input"])
    # structured output настроен на JSON по Pydantic-схеме
    assert captured["response_format"]["mime_type"] == "application/json"
    # ключ схемы в SDK-TypedDict — schema_ (сериализуется в 'schema')
    assert captured["response_format"]["schema_"]["title"] == "CoachReport"
