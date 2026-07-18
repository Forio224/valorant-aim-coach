# -*- coding: utf-8 -*-
"""Stage B3: продуктовый пайплайн upload → YOLO → движок → коуч.

Детектор и коуч инжектируются: тесты гоняют синтетические головы (та же
сцена, что в test_evidence_frames: флик с X-перелётом + hold ниже линии)
без torch и без API. Контракт:
  - сэмплы паспорта = ближайшая к прицелу голова на каждом кадре;
  - эпизоды = segment_episodes по ВСЕМ головам (yolo-путь без identity);
  - статусы DETECTING -> MEASURING -> COACHING в этом порядке;
  - профиль обновляется идемпотентно и попадает в отчёт;
  - коуч получает <= coach_max_images кадров; его провал -> coach_failed,
    но evidence-отчёт остаётся (частичный результат).
"""
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
import pytest

from aim_metrics import Head
from backend.services.analysis_pipeline import (STATUS_COACHING,
                                                STATUS_DETECTING,
                                                STATUS_MEASURING,
                                                PipelineConfig, run_pipeline)
from coach.schema import CoachReport, DrillSelection, FindingExplained
from engine.attribution import attribute_targets
from engine.clip_context import context_for_video
from engine.episodes import segment_episodes
from engine.report import build_report

W, H_SCREEN, FPS = 320, 240, 60.0
HEAD_H = 10.0
N_FRAMES = 200


# ---------------------------------------------------------------- фикстуры

def _write_video(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                             FPS, (W, H_SCREEN))
    assert writer.isOpened(), "cv2 не смог создать синтетическое видео"
    for _ in range(N_FRAMES):
        writer.write(np.full((H_SCREEN, W, 3), 128, dtype=np.uint8))
    writer.release()


@pytest.fixture
def video(tmp_path) -> Path:
    path = tmp_path / "clip.mp4"
    _write_video(path)
    return path


def synthetic_heads() -> Dict[int, List[Head]]:
    """Флик с X-перелётом на кадре 6 + hold, рождённый на 1 HU выше прицела."""
    frames: Dict[int, List[Head]] = {}
    dx = [12, 10, 8, 6, 4, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 9
    for i, d in enumerate(dx):
        frames.setdefault(i, []).append(
            Head(W / 2 + d * HEAD_H, H_SCREEN / 2, height_px=HEAD_H))
    for i in range(100, 130):
        frames.setdefault(i, []).append(
            Head(W / 2, H_SCREEN / 2 - HEAD_H, height_px=HEAD_H))
    return frames


class FakeDetector:
    """Подменяет YOLO: отдаёт заранее заданные головы по кадрам."""

    def __init__(self, heads: Dict[int, List[Head]]):
        self.heads = heads
        self.calls: List[str] = []

    def __call__(self, video_path: str) -> Dict[int, List[Head]]:
        self.calls.append(str(video_path))
        return self.heads


# drill_id core-каталога (tier 1) на метрику — те же id, что в меню промпта.
_DRILL_ID_BY_METRIC = {
    "placement": "placement_t1_range_preaim_walk",
    "consistency": "consistency_t1_vt_ww5t_novice",
    "bias": "bias_t1_vt_1w4ts_novice",
    "correction": "correction_t1_vt_pasu_novice",
}


def _valid_coach_for(report: dict) -> CoachReport:
    """Минимальный CoachReport, проходящий groundedness-валидатор B2."""
    finding = next(f for f in report["findings"] if f["evidence"])
    entry = finding["evidence"][0]
    frame = entry.get("frame", entry.get("frame_start"))
    return CoachReport(
        summary="Портрет игрока без чисел.",
        findings_explained=[FindingExplained(
            metric=finding["metric"],
            explanation="Объяснение без чисел.",
            evidence_frames=[frame],
            confidence=finding["confidence"],
        )],
        drills=[DrillSelection(
            priority=1, drill_id=_DRILL_ID_BY_METRIC[finding["metric"]],
            rationale="Обоснование без чисел.",
        )],
        caveats=[],
    )


class FakeCoach:
    """Подменяет CoachClient: отвечает валидным отчётом или падает."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: List[dict] = []

    def generate(self, evidence: dict, frame_paths, feedback=None):
        self.calls.append({"evidence": evidence,
                           "frames": [Path(p) for p in frame_paths],
                           "feedback": feedback})
        if self.fail:
            raise RuntimeError("Claude API недоступен")
        return _valid_coach_for(evidence)


def _run(video, tmp_path, detector=None, coach=None, **overrides):
    config = PipelineConfig(profile_dir=str(tmp_path / "profiles"),
                            **overrides)
    return run_pipeline(
        str(video), "p1", clip_id="c1", config=config,
        evidence_dir=str(tmp_path / "evidence"),
        detector=detector if detector is not None
        else FakeDetector(synthetic_heads()),
        coach_client=coach if coach is not None else FakeCoach(),
    )


# ------------------------------------------------- числа == прямой прогон движка

def test_report_matches_direct_engine_run(video, tmp_path):
    heads = synthetic_heads()
    result = _run(video, tmp_path)

    ctx = context_for_video(str(video), player_id="p1", clip_id="c1")
    # Тот же поток, что в пайплайне (Фаза 3): атрибуция цели → отфильтрованные
    # сэмплы + мета в consistency. Синтетика — одна голова на кадр, поэтому
    # числа совпадают с наивной «ближайшей», но контракт значений — новый.
    episodes = segment_episodes(heads, ctx)
    attribution = attribute_targets(episodes, ctx)
    samples = [s for s in attribution.samples if s.track_id is not None]
    expected = build_report(ctx, samples, episodes, attribution=attribution)

    got = result.evidence_report
    assert got["schema_version"] == expected["schema_version"]
    assert got["episodes"] == expected["episodes"]
    for got_f, exp_f in zip(got["findings"], expected["findings"]):
        assert got_f["metric"] == exp_f["metric"]
        assert got_f["values"] == exp_f["values"]
        assert got_f["confidence"] == exp_f["confidence"]


def test_training_platform_reaches_report_clip_block(video, tmp_path):
    config = PipelineConfig(profile_dir=str(tmp_path / "profiles"))
    result = run_pipeline(
        str(video), "p1", clip_id="c1", training_platform="kovaaks",
        config=config, evidence_dir=str(tmp_path / "evidence"),
        detector=FakeDetector(synthetic_heads()), coach_client=FakeCoach())
    assert result.evidence_report["clip"]["training_platform"] == "kovaaks"


def test_detector_receives_video_path(video, tmp_path):
    detector = FakeDetector(synthetic_heads())
    _run(video, tmp_path, detector=detector)
    assert detector.calls == [str(video)]


# ------------------------------------------------------------------- статусы

def test_statuses_emitted_in_pipeline_order(video, tmp_path):
    statuses: List[str] = []
    config = PipelineConfig(profile_dir=str(tmp_path / "profiles"))
    run_pipeline(str(video), "p1", clip_id="c1", config=config,
                 evidence_dir=str(tmp_path / "evidence"),
                 detector=FakeDetector(synthetic_heads()),
                 coach_client=FakeCoach(),
                 on_status=statuses.append)
    assert statuses == [STATUS_DETECTING, STATUS_MEASURING, STATUS_COACHING]


# ------------------------------------------------------------------- профиль

def test_profile_saved_and_included_in_report(video, tmp_path):
    result = _run(video, tmp_path)
    profile_path = tmp_path / "profiles" / "p1.json"
    assert profile_path.is_file()
    assert result.evidence_report["profile"]["clips"] == 1


def test_profile_is_idempotent_per_clip_id(video, tmp_path):
    _run(video, tmp_path)
    result = _run(video, tmp_path)          # тот же clip_id -> перезапись
    assert result.evidence_report["profile"]["clips"] == 1


# ------------------------------------------------------------- кадры-улики

def test_evidence_frames_written_to_dir(video, tmp_path):
    result = _run(video, tmp_path)
    assert result.evidence_frames, "улики должны быть отрендерены"
    for path in result.evidence_frames:
        p = Path(path)
        assert p.is_file()
        assert p.name.startswith("frame_") and p.suffix == ".jpg"


# ----------------------------------------------------------------------- коуч

def test_coach_success_returns_report_dict(video, tmp_path):
    result = _run(video, tmp_path)
    assert result.coach_failed is False
    assert result.coach_errors == []
    assert isinstance(result.coach_report, dict)
    assert result.coach_report["summary"]


class _SelectionCoach:
    """Стаб-коуч: возвращает DrillSelection, как настоящий VLM после Task 1."""

    def generate(self, report, frame_paths, feedback=None):
        finding = report["findings"][0]
        return CoachReport(
            summary="ок",
            findings_explained=[FindingExplained(
                metric=finding["metric"], explanation="ок",
                evidence_frames=[], confidence=finding["confidence"])],
            drills=[DrillSelection(
                priority=1, drill_id=_DRILL_ID_BY_METRIC[finding["metric"]],
                rationale="ок")],
            caveats=[],
        )


def test_pipeline_assembles_final_drill_from_catalog(video, tmp_path):
    """После валидации коуча пайплайн подставляет финальный Drill из каталога,
    а не сырой DrillSelection VLM."""
    result = _run(video, tmp_path, coach=_SelectionCoach())

    assert result.coach_failed is False
    expected_metric = result.evidence_report["findings"][0]["metric"]
    drill = result.coach_report["drills"][0]
    assert drill["name"]
    assert drill["dose"]
    assert drill["tier"]
    assert drill["criterion"]
    assert drill["target_metric"] == expected_metric


def test_coach_gets_at_most_max_images_frames(video, tmp_path):
    coach = FakeCoach()
    result = _run(video, tmp_path, coach=coach, coach_max_images=2)
    assert len(result.evidence_frames) > 2, "иначе кап нечем проверять"
    assert len(coach.calls[0]["frames"]) == 2


def test_coach_exception_degrades_to_partial_result(video, tmp_path):
    result = _run(video, tmp_path, coach=FakeCoach(fail=True))
    assert result.coach_failed is True
    assert result.coach_report is None
    assert result.coach_errors, "ошибку нельзя глотать"
    assert result.evidence_report["findings"], "движок остаётся в результате"


# ------------------------------------------------------------- пустой клип

def test_empty_clip_completes_without_coach_crash(video, tmp_path):
    result = _run(video, tmp_path, detector=FakeDetector({}))
    assert result.evidence_report["clip"]["player_id"] == "p1"
    assert result.evidence_frames == []


def test_empty_clip_skips_coach_and_explains(video, tmp_path):
    """Коуча не зовём на пустоту: нечего объяснять и незачем платить."""
    coach = FakeCoach()
    result = _run(video, tmp_path, detector=FakeDetector({}), coach=coach)
    assert coach.calls == []
    assert result.coach_failed is True
    assert result.coach_report is None
    assert any("голов" in err for err in result.coach_errors)


# ------------------------------------------------------------- битый файл

def test_unreadable_video_raises_human_error(tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"this is not a video at all")
    with pytest.raises(ValueError, match="повреждён|не видео"):
        run_pipeline(str(fake), "p1", clip_id="c1",
                     config=PipelineConfig(profile_dir=str(tmp_path / "p")),
                     evidence_dir=str(tmp_path / "e"),
                     detector=FakeDetector({}), coach_client=FakeCoach())


# --------------------------------------------------- петля прогресса (история)

def test_pipeline_emits_drill_progress_from_injected_history(video, tmp_path):
    """history_provider инжектится; drill_progress появляется в отчёте."""
    metric = "consistency"

    def provider(player_id, exclude_clip_id):
        return [{
            "clip_time": "2026-07-01T00:00:00", "clip_id": "prev",
            "assignments": {metric: _DRILL_ID_BY_METRIC[metric]},
            "findings": {metric: {"values": {"mae_hu": 99.0},
                                  "confidence": "diagnosis"}},
        }]

    config = PipelineConfig(profile_dir=str(tmp_path / "profiles"))
    result = run_pipeline(
        str(video), "p1", clip_id="cur", config=config,
        evidence_dir=str(tmp_path / "evidence"),
        detector=FakeDetector(synthetic_heads()), coach_client=FakeCoach(),
        history_provider=provider)

    progress = result.evidence_report["drill_progress"]
    rec = next(r for r in progress if r["metric"] == metric)
    assert rec["anchor_clip_id"] == "prev" and rec["anchor_value"] == 99.0
    assert rec["direction"] == "improved"        # текущий mae << 99 → улучшение


def test_pipeline_no_history_empty_drill_progress(video, tmp_path):
    result = _run(video, tmp_path)               # дефолтный провайдер отсутствует → []
    assert result.evidence_report["drill_progress"] == []
