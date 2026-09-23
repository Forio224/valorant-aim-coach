# -*- coding: utf-8 -*-
"""Синхронизация лога тренажёра с видео.

Запись и прогон стартуют в разные моменты, поэтому у лога и у клипа разные
нули. Спрашивать сдвиг у игрока незачем: видео само даёт моменты, когда
трек цели исчез, а лог — моменты килов. Совмещение двух последовательностей
меток времени даёт и сдвиг, и меру доверия к нему.

Если совпадение слабое, лог не привязывается — разбор деградирует в чистый
видео-режим, как `coach_failed` деградирует при отказе коуча. Молча
приписать клипу чужую статистику хуже, чем не приписать никакой.
"""
import pytest

from engine.trainer_stats import ShotEvent
from engine.trainer_stats.sync import (SyncResult, align_events,
                                       estimate_offset)


def _events(times, hit=True):
    return tuple(ShotEvent(t_seconds=t, hit=hit) for t in times)


# --------------------------------------------------------------- оценка сдвига

def test_finds_known_offset():
    """Лог отстаёт от видео на 4.2 с — ровно это и должно найтись."""
    video = [5.0, 6.5, 9.0, 11.25]
    log = [t - 4.2 for t in video]
    result = estimate_offset(video, log)
    assert result.ok
    assert result.offset_s == pytest.approx(4.2, abs=0.05)
    assert result.matched == 4


def test_zero_offset_when_already_aligned():
    times = [1.0, 2.0, 3.5]
    result = estimate_offset(times, times)
    assert result.ok
    assert result.offset_s == pytest.approx(0.0, abs=1e-6)


def test_tolerates_jitter_within_tolerance():
    """Детектор теряет цель на кадр-другой — сдвиг обязан это переживать."""
    video = [5.0, 6.5, 9.0, 11.25]
    log = [4.98, 6.55, 8.97, 11.30]
    result = estimate_offset(video, log, tolerance_s=0.10)
    assert result.ok
    assert result.matched == 4


def test_extra_video_events_do_not_break_alignment():
    """Детектор нашёл лишние исчезновения (мимо цели пролетел объект)."""
    log = [1.0, 2.0, 3.0]
    video = [0.5, 1.5, 2.5, 3.5, 7.7]      # сдвиг 0.5, плюс один лишний
    result = estimate_offset(video, log)
    assert result.ok
    assert result.offset_s == pytest.approx(-0.5, abs=0.05)
    assert result.matched == 3


# ------------------------------------------------------------------ деградация

def test_unrelated_sequences_are_rejected():
    """Чужой лог не должен приклеиться к клипу."""
    result = estimate_offset([1.0, 2.0, 3.0], [50.0, 91.3, 140.7])
    assert not result.ok
    assert result.offset_s is None


def test_empty_input_is_not_ok():
    assert not estimate_offset([], [1.0, 2.0]).ok
    assert not estimate_offset([1.0, 2.0], []).ok


def test_result_reports_reason_when_rejected():
    """Причина едет в отчёт: игрок должен понимать, почему нет попаданий."""
    result = estimate_offset([1.0, 2.0, 3.0], [50.0, 91.3, 140.7])
    assert result.reason


def test_min_matches_guard_rejects_thin_evidence():
    """Одно-два совпадения — совпадение случая, а не синхронизация."""
    result = estimate_offset([1.0], [1.0], min_matches=3)
    assert not result.ok


# -------------------------------------------------------------- сдвиг событий

def test_align_events_shifts_log_onto_video_clock():
    events = _events([0.0, 1.0, 2.0])
    shifted = align_events(events, SyncResult(offset_s=4.2, matched=3,
                                              total=3, reason=None))
    assert [e.t_seconds for e in shifted] == pytest.approx([4.2, 5.2, 6.2])


def test_align_events_preserves_payload():
    events = (ShotEvent(t_seconds=1.0, hit=False, ttk=0.4, target_id="b1"),)
    shifted = align_events(events, SyncResult(offset_s=1.0, matched=3,
                                              total=3, reason=None))
    assert shifted[0].hit is False
    assert shifted[0].ttk == pytest.approx(0.4)
    assert shifted[0].target_id == "b1"


def test_align_events_without_offset_returns_nothing():
    """Не синхронизировано — значит попаданий на оси видео нет вовсе."""
    events = _events([0.0, 1.0])
    rejected = SyncResult(offset_s=None, matched=0, total=2,
                          reason="совпадений мало")
    assert align_events(events, rejected) == ()


# ------------------------------------------------------------------ инварианты

def test_result_is_frozen():
    result = SyncResult(offset_s=1.0, matched=3, total=3, reason=None)
    with pytest.raises(Exception):
        result.offset_s = 2.0


def test_ok_requires_an_offset():
    assert not SyncResult(offset_s=None, matched=9, total=9, reason="x").ok
