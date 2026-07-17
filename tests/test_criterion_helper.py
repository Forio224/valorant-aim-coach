# -*- coding: utf-8 -*-
"""Общий хелпер критерия (Фаза 2B): нейтральный dict + единая нормировка."""
from engine.metrics.criterion import (compute_metric_criterion, normalize,
                                       CORE_METRICS)


def test_core_metrics_order():
    assert CORE_METRICS == ("placement", "consistency", "bias", "correction")


def test_consistency_neutral_dict():
    m = compute_metric_criterion("consistency", {"mae_hu": 5.0})
    assert m == {"value_key": "mae_hu", "comparator": "<", "target": 4.25,
                 "baseline": 5.0, "directional_meaningful": True}


def test_bias_baseline_is_abs_rounded():
    m = compute_metric_criterion("bias", {"y_bias_hu": -0.6})
    assert m["value_key"] == "y_bias_hu" and m["comparator"] == "<"
    assert m["baseline"] == 0.6 and m["target"] == 0.3
    assert m["directional_meaningful"] is True


def test_placement_target_and_int_baseline():
    m = compute_metric_criterion("placement", {"total": 10, "below": 7})
    assert m["value_key"] == "below" and m["comparator"] == "count_le"
    assert m["target"] == 2.0 and m["baseline"] == 7.0


def test_correction_picks_worst_axis():
    m = compute_metric_criterion(
        "correction", {"x_overshoots": 1, "x_undershoots": 0,
                       "y_overshoots": 3, "y_undershoots": 0,
                       "flicks_analysed": 5})
    assert m["value_key"] == "y_overshoots" and m["comparator"] == "direction"
    assert m["target"] is None and m["baseline"] == 3.0
    assert m["directional_meaningful"] is True


def test_correction_degenerate_count_zero():
    m = compute_metric_criterion(
        "correction", {"x_overshoots": 0, "x_undershoots": 0,
                       "y_overshoots": 0, "y_undershoots": 0,
                       "flicks_analysed": 4})
    assert m["value_key"] == "flicks_analysed" and m["baseline"] == 0.0
    assert m["directional_meaningful"] is False


def test_missing_data_marks_not_meaningful():
    m = compute_metric_criterion("consistency", {})
    assert m["baseline"] is None and m["directional_meaningful"] is False


def test_normalize_bias_abs_and_round():
    assert normalize("y_bias_hu", -0.6001) == 0.6
    assert normalize("mae_hu", 4.2506) == 4.251
    assert normalize("below", 7.0) == 7
    assert normalize("x_overshoots", 3.0) == 3
    assert normalize("mae_hu", None) is None


def test_build_criterion_agrees_with_helper():
    """build_criterion берёт числа из того же хелпера (single source)."""
    from coach.drill_catalog import build_criterion
    values = {"mae_hu": 5.0}
    m = compute_metric_criterion("consistency", values)
    sc = build_criterion("consistency", values)
    assert sc.value_key == m["value_key"] and sc.comparator == m["comparator"]
    assert sc.target == m["target"] and sc.baseline == m["baseline"]


def test_engine_does_not_import_coach():
    """Анти-цикл: ни один модуль engine/ не импортирует coach/."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parent.parent / "engine"
    offenders = [p.name for p in root.rglob("*.py")
                 if re.search(r"^\s*(from|import)\s+coach",
                              p.read_text(encoding="utf-8"), re.MULTILINE)]
    assert offenders == [], f"engine → coach импорт запрещён: {offenders}"
