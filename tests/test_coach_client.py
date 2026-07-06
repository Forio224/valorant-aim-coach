# -*- coding: utf-8 -*-
"""Тесты CoachClient: сборка мультимодального сообщения, кап картинок, модель (Stage B1)."""
import base64
import io
import json
from pathlib import Path

import pytest

from coach.client import DEFAULT_MODEL, MAX_IMAGES, CoachClient
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


def _client() -> CoachClient:
    return CoachClient(api_key="test-key")


def test_default_model():
    assert DEFAULT_MODEL == "claude-sonnet-5"
    assert _client().model == "claude-sonnet-5"


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("COACH_MODEL", "claude-haiku-4-5")
    assert CoachClient(api_key="test-key").model == "claude-haiku-4-5"


def test_explicit_model_beats_env(monkeypatch):
    monkeypatch.setenv("COACH_MODEL", "claude-haiku-4-5")
    c = CoachClient(api_key="test-key", model="claude-sonnet-4-6")
    assert c.model == "claude-sonnet-4-6"


def test_build_content_starts_with_report_text(report, frames_dir):
    content = _client().build_content(report, sorted(frames_dir.glob("*.jpg")))
    assert content[0]["type"] == "text"
    assert '"player_id": "friend"' in content[0]["text"]


def test_build_content_caps_images(report, frames_dir):
    paths = sorted(frames_dir.glob("*.jpg"))
    assert len(paths) == 12
    content = _client().build_content(report, paths)
    images = [b for b in content if b["type"] == "image"]
    assert len(images) == MAX_IMAGES == 10


def test_image_blocks_are_base64_jpeg_with_frame_labels(report, frames_dir):
    paths = [frames_dir / "frame_000177.jpg"]
    content = _client().build_content(report, paths)
    images = [b for b in content if b["type"] == "image"]
    assert len(images) == 1
    src = images[0]["source"]
    assert src["type"] == "base64"
    assert src["media_type"] == "image/jpeg"
    assert base64.b64decode(src["data"]) == FAKE_JPEG
    # перед картинкой — текстовая подпись с номером кадра
    idx = content.index(images[0])
    assert content[idx - 1]["type"] == "text"
    assert "177" in content[idx - 1]["text"]


def test_build_content_appends_feedback_as_final_text_block(report, frames_dir):
    content = _client().build_content(
        report,
        sorted(frames_dir.glob("*.jpg")),
        feedback="кадр 999 не существует",
    )
    assert content[-1]["type"] == "text"
    assert "кадр 999 не существует" in content[-1]["text"]


def test_build_content_without_feedback_has_no_trailing_text(report, frames_dir):
    content = _client().build_content(report, sorted(frames_dir.glob("*.jpg")))
    assert content[-1]["type"] == "image"


def test_generate_returns_parsed_coach_report(report, frames_dir, monkeypatch):
    coach_report = CoachReport(
        summary="ок", findings_explained=[], drills=[], caveats=[]
    )

    captured: dict = {}

    class StubMessages:
        def parse(self, **kwargs):
            captured.update(kwargs)

            class Resp:
                parsed_output = coach_report

            return Resp()

    class StubAnthropic:
        messages = StubMessages()

    c = _client()
    monkeypatch.setattr(c, "_client", StubAnthropic())
    result = c.generate(report, sorted(frames_dir.glob("*.jpg")))

    assert result is coach_report
    assert captured["model"] == "claude-sonnet-5"
    assert captured["output_format"] is CoachReport
    assert isinstance(captured["system"], str) and len(captured["system"]) > 100
    msgs = captured["messages"]
    assert msgs[0]["role"] == "user"
    assert any(b["type"] == "image" for b in msgs[0]["content"])


def _stub_client(monkeypatch, c: CoachClient) -> dict:
    """Подменяет SDK-клиент заглушкой, возвращает пойманные kwargs parse()."""
    captured: dict = {}

    class StubMessages:
        def parse(self, **kwargs):
            captured.update(kwargs)

            class Resp:
                parsed_output = CoachReport(
                    summary="ок", findings_explained=[], drills=[], caveats=[]
                )

            return Resp()

    class StubAnthropic:
        messages = StubMessages()

    monkeypatch.setattr(c, "_client", StubAnthropic())
    return captured


def test_generate_disables_thinking_and_sends_effort(report, frames_dir, monkeypatch):
    c = _client()
    captured = _stub_client(monkeypatch, c)
    c.generate(report, sorted(frames_dir.glob("*.jpg")))
    # thinking выключен: без него Sonnet 5 жёг бы adaptive-мышление (output-токены)
    assert captured["thinking"] == {"type": "disabled"}
    # effort по умолчанию low, format остаётся от output_format (merge в SDK)
    assert captured["output_config"] == {"effort": "low"}


def test_generate_omits_effort_when_empty(report, frames_dir, monkeypatch):
    c = CoachClient(api_key="test-key", effort="")
    captured = _stub_client(monkeypatch, c)
    c.generate(report, sorted(frames_dir.glob("*.jpg")))
    # пустой effort -> output_config не шлём (модели без поддержки effort → 400)
    assert "output_config" not in captured
    assert captured["thinking"] == {"type": "disabled"}


def test_effort_from_env(monkeypatch):
    monkeypatch.setenv("COACH_EFFORT", "medium")
    assert CoachClient(api_key="test-key").effort == "medium"


def test_build_content_shrinks_wide_frame(report, tmp_path):
    from PIL import Image

    from coach.client import COACH_IMAGE_MAX_WIDTH

    d = tmp_path / "evidence"
    d.mkdir()
    wide = d / "frame_000177.jpg"
    Image.new("RGB", (2000, 1120), (30, 40, 50)).save(wide, format="JPEG")

    content = _client().build_content(report, [wide])
    image = next(b for b in content if b["type"] == "image")
    decoded = Image.open(io.BytesIO(base64.b64decode(image["source"]["data"])))
    assert decoded.width == COACH_IMAGE_MAX_WIDTH
    assert decoded.height == 573  # аспект сохранён: round(1120 * 1024/2000)


def test_build_content_keeps_small_frame_untouched(report, tmp_path):
    from PIL import Image

    d = tmp_path / "evidence"
    d.mkdir()
    small = d / "frame_000177.jpg"
    Image.new("RGB", (640, 360), (30, 40, 50)).save(small, format="JPEG")
    original = small.read_bytes()

    content = _client().build_content(report, [small])
    image = next(b for b in content if b["type"] == "image")
    # маленький кадр отдаётся байт-в-байт, без перекодирования
    assert base64.b64decode(image["source"]["data"]) == original
