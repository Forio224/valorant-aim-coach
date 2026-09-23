# -*- coding: utf-8 -*-
"""Режим аим-тренажёра в продуктовом пайплайне.

Проверяется то, что отличает клип тренажёра от игрового:
  - источник целей по умолчанию — цветовой детектор, а не YOLO по головам;
  - пороги движка берутся из профиля платформы, а не из валорантовой
    калибровки;
  - лог прогона, если он приложен, синхронизируется с видео и даёт секцию
    попаданий;
  - любая беда с логом деградирует в разбор без попаданий, а не в падение
    сессии — тот же контракт, что у `coach_failed`.

Детектор и коуч инжектируются, как в test_analysis_pipeline: ни torch, ни
внешнего API здесь нет.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.services.analysis_pipeline import PipelineConfig, run_pipeline
from engine.platform_profile import TRAINER, VALORANT

from test_analysis_pipeline import (FakeCoach, FakeDetector, synthetic_heads,
                                    _write_video)

KOVAAKS_CSV = """Kill #,Timestamp,Bot,Weapon,TTK,Damage Done,Damage Possible,Efficiency,Cheated
1,13:37:57.929,Bot 1,Gun,0.512s,100,100,1,0
2,13:37:58.741,Bot 2,Gun,0.633s,100,100,1,0

Weapon,Shots,Hits,Damage Done,Damage Possible
Gun,8,2,200,800

Scenario:,VT Pasu Rasp Intermediate S5
Score:,1284.56
Avg TTK:,0.572
"""


@pytest.fixture
def video(tmp_path) -> Path:
    path = tmp_path / "clip.mp4"
    _write_video(path)
    return path


def _stats(tmp_path, text=KOVAAKS_CSV) -> str:
    path = tmp_path / "run Stats.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _run(video, tmp_path, **kw):
    config = kw.pop("config", None) or PipelineConfig(
        profile_dir=str(tmp_path / "profiles"))
    return run_pipeline(
        str(video), "p1", clip_id="c1", config=config,
        evidence_dir=str(tmp_path / "evidence"),
        detector=kw.pop("detector", FakeDetector(synthetic_heads())),
        coach_client=FakeCoach(), **kw)


# ------------------------------------------------------------- профиль платформы

@pytest.mark.parametrize("platform,expected", [
    ("kovaaks", TRAINER),
    ("aimbeast", TRAINER),
    ("ingame", VALORANT),
    (None, VALORANT),
])
def test_config_resolves_platform_profile(platform, expected):
    from backend.services.analysis_pipeline import profile_for
    assert profile_for(platform) is expected


# ------------------------------------------------------------- детектор по умолчанию

@pytest.mark.parametrize("platform", ["kovaaks", "aimbeast"])
def test_trainer_clip_defaults_to_colour_detector(platform):
    """Без явного детектора клип тренажёра не должен уходить в YOLO по
    головам: веса heads_v3 на сферах не работают."""
    from backend.services.analysis_pipeline import default_detector_for
    from backend.trainer_target_detector import SOURCE_NAME

    detector = default_detector_for(platform, PipelineConfig())
    assert detector.source == SOURCE_NAME


@pytest.mark.parametrize("platform", ["ingame", None])
def test_game_clip_defaults_to_yolo(platform):
    from backend.services.analysis_pipeline import (YOLO_SOURCE_NAME,
                                                    default_detector_for)

    detector = default_detector_for(platform, PipelineConfig())
    assert detector.source == YOLO_SOURCE_NAME


def test_explicit_detector_still_wins(video, tmp_path):
    """Инъекция детектора — контракт тестов и CLI, платформа его не отменяет."""
    detector = FakeDetector(synthetic_heads())
    _run(video, tmp_path, training_platform="kovaaks", detector=detector)
    assert detector.calls == [str(video)]


# ------------------------------------------------------------------ лог прогона

def test_stats_produce_shots_section(video, tmp_path):
    result = _run(video, tmp_path, training_platform="kovaaks",
                  stats_path=_stats(tmp_path))
    shots = result.evidence_report.get("shots")
    assert shots is not None
    assert shots["source"] == "kovaaks"
    assert shots["shots"] == 8 and shots["hits"] == 2
    assert shots["measured_by"] == "trainer_log"


def test_without_stats_there_is_no_shots_section(video, tmp_path):
    result = _run(video, tmp_path, training_platform="kovaaks")
    assert "shots" not in result.evidence_report


def test_game_clip_ignores_stats(video, tmp_path):
    """Лог тренажёра к игровому клипу отношения не имеет."""
    result = _run(video, tmp_path, training_platform="ingame",
                  stats_path=_stats(tmp_path))
    assert "shots" not in result.evidence_report


# ------------------------------------------------------------------ деградация

def test_broken_stats_do_not_fail_the_session(video, tmp_path):
    """Битый лог: разбор остаётся, секция объясняет отказ."""
    path = tmp_path / "broken.csv"
    path.write_text("мусор\n", encoding="utf-8")
    result = _run(video, tmp_path, training_platform="kovaaks",
                  stats_path=str(path))
    assert result.evidence_report["findings"]          # движок отработал
    shots = result.evidence_report.get("shots")
    assert shots is not None and shots["synced"] is False
    assert shots["note"]


def test_missing_stats_file_does_not_fail_the_session(video, tmp_path):
    result = _run(video, tmp_path, training_platform="kovaaks",
                  stats_path=str(tmp_path / "нет.csv"))
    assert result.evidence_report["findings"]
    assert result.evidence_report["shots"]["synced"] is False


def test_unsynced_log_keeps_trainer_summary(video, tmp_path):
    """Синтетические головы и реальный лог не совпадут по времени — сводка
    тренажёра при этом остаётся верной, она не про кадры."""
    result = _run(video, tmp_path, training_platform="kovaaks",
                  stats_path=_stats(tmp_path))
    shots = result.evidence_report["shots"]
    assert shots["shots"] == 8
    assert shots["accuracy"] == pytest.approx(0.25)
