# -*- coding: utf-8 -*-
"""Метрики попаданий из лога тренажёра.

Движок геометрический: он видит офсет прицела от цели, но не момент
выстрела, поэтому TTK и accuracy посчитать не может (см.
docs/analysis/2026-07-15-engine-weak-spots.md). Лог тренажёра закрывает
ровно эту дыру.

Секция опциональна и честна: без лога её нет, при неудачной синхронизации
она присутствует только как причина отказа. Числа, которые движок не
измерял, помечены источником — иначе валидатор коуча не сможет отличить
измеренное от приписанного.
"""
import pytest

from engine.metrics.shots import ShotMetrics, compute_shot_metrics
from engine.trainer_stats import ShotEvent, TrainerSession
from engine.trainer_stats.sync import SyncResult

OK_SYNC = SyncResult(offset_s=1.0, matched=4, total=4, reason=None)
BAD_SYNC = SyncResult(offset_s=None, matched=0, total=4,
                      reason="лог не удалось привязать к клипу")


def _session(ttks=(0.40, 0.50, 0.60, 0.80), shots=16, hits=4, **kw):
    events = tuple(ShotEvent(t_seconds=float(i), hit=True, ttk=t,
                             target_id=f"Bot {i}")
                   for i, t in enumerate(ttks))
    return TrainerSession(platform="kovaaks", events=events, shots=shots,
                          hits=hits, scenario="VT Pasu Rasp Intermediate S5",
                          **kw)


# ------------------------------------------------------------------- базовое

def test_reports_accuracy_from_trainer_summary():
    m = compute_shot_metrics(_session(), OK_SYNC)
    assert m.shots == 16
    assert m.hits == 4
    assert m.accuracy == pytest.approx(0.25)


def test_reports_ttk_statistics():
    m = compute_shot_metrics(_session(), OK_SYNC)
    assert m.ttk_median == pytest.approx(0.55)
    assert m.ttk_mean == pytest.approx(0.575)
    assert m.ttk_std == pytest.approx(0.170, abs=0.01)


def test_kills_counted_from_events():
    assert compute_shot_metrics(_session(), OK_SYNC).kills == 4


def test_carries_scenario_and_platform():
    m = compute_shot_metrics(_session(), OK_SYNC)
    assert m.platform == "kovaaks"
    assert m.scenario == "VT Pasu Rasp Intermediate S5"


def test_records_sync_quality():
    """Качество привязки — часть доказательной базы, а не служебная деталь."""
    m = compute_shot_metrics(_session(), OK_SYNC)
    assert m.sync_matched == 4
    assert m.sync_offset_s == pytest.approx(1.0)


# ---------------------------------------------------------------- деградация

def test_failed_sync_keeps_summary_but_drops_timeline():
    """Сводка тренажёра верна и без синхронизации — она не про кадры.
    А вот привязка к эпизодам без общего нуля невозможна."""
    m = compute_shot_metrics(_session(), BAD_SYNC)
    assert m.accuracy == pytest.approx(0.25)
    assert m.synced is False
    assert m.note


def test_session_without_events_has_no_ttk():
    session = TrainerSession(platform="kovaaks", events=(), shots=10, hits=0)
    m = compute_shot_metrics(session, BAD_SYNC)
    assert m.ttk_median is None
    assert m.kills == 0
    assert m.accuracy == pytest.approx(0.0)


def test_session_without_summary_has_no_accuracy():
    session = TrainerSession(platform="aimbeast",
                             events=(ShotEvent(1.0, True, 0.5),))
    m = compute_shot_metrics(session, OK_SYNC)
    assert m.accuracy is None
    assert m.ttk_median == pytest.approx(0.5)


def test_events_without_ttk_do_not_break_statistics():
    session = TrainerSession(platform="kovaaks",
                             events=(ShotEvent(1.0, True),
                                     ShotEvent(2.0, True, 0.5)))
    m = compute_shot_metrics(session, OK_SYNC)
    assert m.ttk_median == pytest.approx(0.5)


def test_single_ttk_has_no_std():
    session = TrainerSession(platform="kovaaks",
                             events=(ShotEvent(1.0, True, 0.5),))
    assert compute_shot_metrics(session, OK_SYNC).ttk_std is None


# ------------------------------------------------------------- блок в отчёте

def test_report_block_is_json_ready():
    block = compute_shot_metrics(_session(), OK_SYNC).to_report_block()
    import json
    json.dumps(block, ensure_ascii=False)          # не должно упасть
    assert block["source"] == "kovaaks"
    assert block["accuracy"] == pytest.approx(0.25)


def test_report_block_marks_measurement_source():
    """Числа пришли из тренажёра, а не из движка — валидатор коуча должен
    видеть это явно, иначе не отличит измеренное от выдуманного."""
    block = compute_shot_metrics(_session(), OK_SYNC).to_report_block()
    assert block["measured_by"] == "trainer_log"


def test_rejected_sync_block_states_the_reason():
    block = compute_shot_metrics(_session(), BAD_SYNC).to_report_block()
    assert block["synced"] is False
    assert "привяз" in block["note"]


def test_metrics_are_frozen():
    m = compute_shot_metrics(_session(), OK_SYNC)
    with pytest.raises(Exception):
        m.accuracy = 0.99


def test_is_shot_metrics_instance():
    assert isinstance(compute_shot_metrics(_session(), OK_SYNC), ShotMetrics)
