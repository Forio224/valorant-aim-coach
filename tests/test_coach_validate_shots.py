# -*- coding: utf-8 -*-
"""Заземление чисел секции попаданий.

Валидатор сверяет каждое число ответа коуча с evidence-JSON. Секция
попаданий приносит числа, которых движок не измерял (accuracy, TTK), —
значит они обязаны попасть в пул допустимых, иначе честная ссылка на
статистику тренажёра будет забракована как выдумка.

Обратное тоже важно: число, которого в секции нет, заземляться не должно.
"""
from coach.validate import _known_numbers

REPORT = {
    "findings": [],
    "episodes": [],
    "clip": {"training_platform": "kovaaks"},
    "shots": {
        "source": "kovaaks",
        "measured_by": "trainer_log",
        "scenario": "VT Pasu Rasp Intermediate S5",
        "shots": 16,
        "hits": 4,
        "accuracy": 0.25,
        "kills": 4,
        "ttk_median_s": 0.55,
        "ttk_mean_s": 0.575,
        "ttk_p95_s": 0.77,
        "ttk_std_s": 0.17,
        "synced": True,
        "sync_matched": 4,
        "sync_total": 4,
        "sync_offset_s": 1.5,
        "note": None,
    },
}


def test_shot_numbers_are_grounded():
    pool = _known_numbers(REPORT)
    for value in (16, 4, 0.25, 0.55, 0.575, 0.77, 0.17):
        assert value in pool, f"{value} должно заземляться секцией попаданий"


def test_unrelated_number_is_not_grounded():
    assert 9.99 not in _known_numbers(REPORT)


def test_booleans_are_not_numbers():
    """`synced: True` — флаг, а не измерение: 1.0 заземлять нельзя."""
    assert 1.0 not in _known_numbers(REPORT)


def test_report_without_shots_section_is_unaffected():
    report = {"findings": [], "episodes": [], "clip": {}}
    assert _known_numbers(report) == []


def test_null_fields_do_not_break_the_pool():
    report = dict(REPORT)
    report["shots"] = dict(REPORT["shots"],
                           accuracy=None, ttk_median_s=None, shots=None)
    pool = _known_numbers(report)
    assert 4 in pool
    assert None not in pool
