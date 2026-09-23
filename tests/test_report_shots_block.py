# -*- coding: utf-8 -*-
"""Секция попаданий в evidence-JSON.

Контракт тот же, что у внешнего ранка KovaaK's: блок с чужими измерениями
движок не пересчитывает, а переносит, помечая источник. Отличие в том, что
секция попаданий появляется только при наличии лога — у игрового клипа её
нет вовсе, и это не отсутствие данных, а отсутствие самого понятия.
"""
import json

import pytest

from engine.clip_context import ClipContext
from engine.metrics.shots import compute_shot_metrics
from engine.report import SCHEMA_VERSION, build_report
from engine.trainer_stats import ShotEvent, TrainerSession
from engine.trainer_stats.sync import SyncResult


def _ctx(platform="kovaaks"):
    return ClipContext(player_id="p", clip_id="c", fps=60.0, width=1920,
                       height=1080, frame_count=600,
                       training_platform=platform)


def _shots_block():
    session = TrainerSession(
        platform="kovaaks", scenario="VT Pasu Rasp Intermediate S5",
        shots=16, hits=4,
        events=tuple(ShotEvent(float(i), True, 0.4 + i / 10)
                     for i in range(4)))
    sync = SyncResult(offset_s=1.5, matched=4, total=4, reason=None)
    return compute_shot_metrics(session, sync).to_report_block()


# --------------------------------------------------------------------- схема

def test_schema_version_bumped_for_shots_section():
    """Новая секция — новая версия схемы: валидатор и фронт читают её."""
    assert SCHEMA_VERSION == "1.5"


# ------------------------------------------------------------- наличие блока

def test_shots_block_lands_in_report():
    report = build_report(_ctx(), [], [], shots=_shots_block())
    assert "shots" in report
    assert report["shots"]["source"] == "kovaaks"
    assert report["shots"]["accuracy"] == pytest.approx(0.25)


def test_game_clip_has_no_shots_section():
    """У игрового клипа выстрелы не измеряются ничем — блока быть не должно."""
    report = build_report(_ctx(platform="ingame"), [], [])
    assert "shots" not in report


def test_report_stays_json_serialisable_with_shots():
    report = build_report(_ctx(), [], [], shots=_shots_block())
    json.dumps(report, ensure_ascii=False, allow_nan=False)


def test_shots_block_is_carried_verbatim():
    """Движок числа лога не пересчитывает — как и внешний ранк KovaaK's."""
    block = _shots_block()
    report = build_report(_ctx(), [], [], shots=block)
    assert report["shots"] == block
