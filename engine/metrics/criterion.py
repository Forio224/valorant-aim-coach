# -*- coding: utf-8 -*-
"""Числовое ядро критерия успеха — общий слой Фазы 1 (build_criterion) и
Фазы 2B (compute_drill_progress).

Живёт в engine/ и возвращает НЕЙТРАЛЬНЫЙ dict, НЕ SuccessCriterion:
coach.schema не импортируется движком (иначе цикл coach.drill_catalog →
engine → coach.schema и инверсия слоёв — движок автономен под CLI
aim_metrics.py). build_criterion (coach/) оборачивает dict в SuccessCriterion
+ человеческий text. normalize держит anchor и current в одном baseline-space.
"""
from typing import Optional

CORE_METRICS = ("placement", "consistency", "bias", "correction")

PLACEMENT_TARGET_FRACTION = 0.2
CONSISTENCY_IMPROVEMENT = 0.15     # MAE < base * 0.85
BIAS_HALVE_FACTOR = 0.5

_COUNT_KEYS = ("below", "x_overshoots", "x_undershoots",
               "y_overshoots", "y_undershoots", "flicks_analysed")


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    return None if x is None else round(x, digits)


def normalize(value_key: str, raw: Optional[float]) -> Optional[float]:
    """Сырое значение метрики → baseline-space по value_key. ТОТ ЖЕ трансформ,
    что compute_metric_criterion кладёт в baseline (вкл. округление)."""
    if raw is None:
        return None
    if value_key.endswith("_bias_hu"):
        return _r(abs(raw))
    if value_key in _COUNT_KEYS:
        return int(round(raw))
    return _r(raw)


def compute_metric_criterion(metric: str, values: dict) -> dict:
    """Нейтральный dict {value_key, comparator, target, baseline,
    directional_meaningful}. directional_meaningful=False = дельту по критерию
    считать нельзя (нет данных / вырожденец correction)."""
    if metric == "placement":
        total, below = values.get("total"), values.get("below")
        if total is None or below is None:
            return {"value_key": "below", "comparator": "count_le",
                    "target": None, "baseline": None,
                    "directional_meaningful": False}
        return {"value_key": "below", "comparator": "count_le",
                "target": float(round(PLACEMENT_TARGET_FRACTION * total)),
                "baseline": float(int(below)), "directional_meaningful": True}
    if metric == "consistency":
        base = values.get("mae_hu")
        if base is None:
            return {"value_key": "mae_hu", "comparator": "<", "target": None,
                    "baseline": None, "directional_meaningful": False}
        return {"value_key": "mae_hu", "comparator": "<",
                "target": _r(base * (1 - CONSISTENCY_IMPROVEMENT)),
                "baseline": _r(base), "directional_meaningful": True}
    if metric == "bias":
        raw = values.get("y_bias_hu")
        if raw is None:
            return {"value_key": "y_bias_hu", "comparator": "<", "target": None,
                    "baseline": None, "directional_meaningful": False}
        base = abs(raw)
        return {"value_key": "y_bias_hu", "comparator": "<",
                "target": _r(base * BIAS_HALVE_FACTOR), "baseline": _r(base),
                "directional_meaningful": True}
    if metric == "correction":
        pairs = [("x_overshoots", values.get("x_overshoots", 0)),
                 ("x_undershoots", values.get("x_undershoots", 0)),
                 ("y_overshoots", values.get("y_overshoots", 0)),
                 ("y_undershoots", values.get("y_undershoots", 0))]
        value_key, count = max(pairs, key=lambda p: p[1])
        if count == 0:
            value_key = "flicks_analysed"
        return {"value_key": value_key, "comparator": "direction",
                "target": None, "baseline": float(count),
                "directional_meaningful": count > 0}
    raise ValueError(f"неизвестная метрика критерия: {metric}")
