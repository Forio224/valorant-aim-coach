# -*- coding: utf-8 -*-
"""Метрики попаданий: то, чего геометрический движок измерить не может.

Движок работает с офсетом прицела от цели и не видит ни момента выстрела,
ни момента попадания — поэтому TTK и accuracy в нём отсутствуют
принципиально, а не по недоделке (docs/analysis/2026-07-15-engine-weak-spots.md).
Лог тренажёра эти числа приносит готовыми.

Два правила, от которых зависит доверие к разбору:

1. Источник помечается явно (`measured_by: trainer_log`). Валидатор коуча
   сверяет каждое число ответа с evidence-JSON; числа, которых движок не
   мерил, обязаны быть отличимы от измеренных им.
2. Сводка тренажёра (shots/hits) верна независимо от синхронизации — она не
   про кадры. Привязка к эпизодам без общего нуля невозможна, и тогда
   секция честно говорит, что синхронизации не было.
"""
import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from engine.trainer_stats import TrainerSession
from engine.trainer_stats.sync import SyncResult


def _round(value: Optional[float], digits: int = 3) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Линейная интерполяция по отсортированному ряду; None на пустом."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class ShotMetrics:
    """Секция попаданий evidence-JSON."""
    platform: str
    scenario: Optional[str]

    shots: Optional[int]
    hits: Optional[int]
    accuracy: Optional[float]
    kills: int

    ttk_median: Optional[float]
    ttk_mean: Optional[float]
    ttk_p95: Optional[float]
    ttk_std: Optional[float]

    synced: bool
    sync_matched: int
    sync_total: int
    sync_offset_s: Optional[float]
    note: Optional[str]

    def to_report_block(self) -> Dict[str, Any]:
        """JSON-готовый блок для `build_report`."""
        return {
            "source": self.platform,
            "measured_by": "trainer_log",
            "scenario": self.scenario,
            "shots": self.shots,
            "hits": self.hits,
            "accuracy": _round(self.accuracy, 4),
            "kills": self.kills,
            "ttk_median_s": _round(self.ttk_median),
            "ttk_mean_s": _round(self.ttk_mean),
            "ttk_p95_s": _round(self.ttk_p95),
            "ttk_std_s": _round(self.ttk_std),
            "synced": self.synced,
            "sync_matched": self.sync_matched,
            "sync_total": self.sync_total,
            "sync_offset_s": _round(self.sync_offset_s),
            "note": self.note,
        }


def compute_shot_metrics(session: TrainerSession,
                         sync: SyncResult) -> ShotMetrics:
    """Метрики попаданий по логу прогона и итогу его привязки к клипу."""
    ttks: List[float] = [e.ttk for e in session.events if e.ttk is not None]

    return ShotMetrics(
        platform=session.platform,
        scenario=session.scenario,
        shots=session.shots,
        hits=session.hits,
        accuracy=session.accuracy,
        kills=sum(1 for e in session.events if e.hit),
        ttk_median=statistics.median(ttks) if ttks else None,
        ttk_mean=statistics.fmean(ttks) if ttks else None,
        ttk_p95=_percentile(ttks, 0.95),
        ttk_std=statistics.stdev(ttks) if len(ttks) > 1 else None,
        synced=sync.ok,
        sync_matched=sync.matched,
        sync_total=sync.total,
        sync_offset_s=sync.offset_s,
        note=sync.reason,
    )
