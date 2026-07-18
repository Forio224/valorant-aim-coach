# -*- coding: utf-8 -*-
"""Stage 7 (Фаза 2B): петля прогресса на engine-сигнале.

Отвечает на «сдвинулась ли метрика после совета?»: кумулятивная дельта от
anchor'а (первый флаг неразрешённой серии) к текущему клипу. Разрыв серии —
по резолюции метрики (value достиг target при confidence ≥ hypothesis), НЕ по
отсутствию дрилла (топ-2-трим/невыбор VLM не сбрасывают anchor). correction
(target-less прокси) — единый anchor, не рвётся. confidence = min(anchor,
current). Числа считает движок; каузальности нет — только дельта+направление.
"""
from typing import List, Optional, Sequence

from engine.metrics.criterion import (CORE_METRICS, compute_metric_criterion,
                                       normalize)

_CONF_ORDER = {"insufficient": 0, "hypothesis": 1, "diagnosis": 2}


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    return None if x is None else round(x, digits)


def _min_conf(a: str, b: str) -> str:
    return a if _CONF_ORDER[a] <= _CONF_ORDER[b] else b


def _meets(comparator: str, target: Optional[float], value: Optional[float],
           conf: str) -> bool:
    """Резолюция: value удовлетворил target при доверяемой confidence."""
    if target is None or value is None or conf == "insufficient":
        return False
    if comparator == "<":
        return value < target
    if comparator == "count_le":
        return value <= target
    return False                       # direction: порога нет


def _open_series_anchor(metric: str, history: Sequence[dict]) -> Optional[dict]:
    """anchor текущей неразрешённой серии, либо None (не флагнута / разрешена и
    не рефлагнута). Разрыв — по резолюции, не по отсутствию дрилла."""
    flagged = [s for s in history
               if metric in s.get("assignments", {}) and metric in s["findings"]]
    if not flagged:
        return None
    anchor = flagged[0]
    while True:
        m = compute_metric_criterion(metric, anchor["findings"][metric]["values"])
        target, comparator, value_key = m["target"], m["comparator"], m["value_key"]
        if target is None:             # correction: единый anchor, не рвётся
            return anchor
        resolved = None
        for s in history:
            if s["clip_time"] <= anchor["clip_time"]:
                continue
            f = s["findings"].get(metric)
            if f is None or f["confidence"] == "insufficient":
                continue
            val = normalize(value_key, f["values"].get(value_key))
            if _meets(comparator, target, val, f["confidence"]):
                resolved = s
                break
        if resolved is None:
            return anchor
        nxt = next((s for s in flagged
                    if s["clip_time"] > resolved["clip_time"]), None)
        if nxt is None:
            return None
        anchor = nxt


def compute_drill_progress(findings: Sequence[dict],
                           drill_history: Sequence[dict]) -> List[dict]:
    """Записи прогресса по метрикам с открытой серией (порядок CORE_METRICS)."""
    history = sorted(drill_history, key=lambda s: s["clip_time"])
    findings_by_metric = {f["metric"]: f for f in findings}
    records: List[dict] = []
    for metric in CORE_METRICS:
        anchor = _open_series_anchor(metric, history)
        if anchor is None:
            continue
        m = compute_metric_criterion(metric, anchor["findings"][metric]["values"])
        value_key, comparator, target = m["value_key"], m["comparator"], m["target"]
        anchor_conf = anchor["findings"][metric]["confidence"]
        anchor_value = m["baseline"] if m["directional_meaningful"] else None

        cur = findings_by_metric.get(metric)
        current_conf = cur["confidence"] if cur else "insufficient"
        current_value = (normalize(value_key, cur["values"].get(value_key))
                         if cur else None)

        if anchor_value is None or current_value is None:
            delta, direction, confidence, resolved_now = (
                None, "insufficient", "insufficient", False)
        else:
            delta = _r(current_value - anchor_value)
            direction = ("flat" if delta == 0
                         else "improved" if current_value < anchor_value
                         else "regressed")
            confidence = _min_conf(anchor_conf, current_conf)
            resolved_now = _meets(comparator, target, current_value, current_conf)

        drill_id = next((s["assignments"][metric] for s in reversed(history)
                         if metric in s.get("assignments", {})), None)
        series_len = sum(1 for s in history
                         if s["clip_time"] >= anchor["clip_time"]
                         and metric in s["findings"])
        records.append({
            "metric": metric, "drill_id": drill_id, "value_key": value_key,
            "comparator": comparator, "anchor_value": anchor_value,
            "anchor_clip_id": anchor["clip_id"], "current_value": current_value,
            "delta": delta, "direction": direction, "confidence": confidence,
            "series_len": series_len, "resolved_now": resolved_now,
            "order_uncertain": True,
        })
    return records
