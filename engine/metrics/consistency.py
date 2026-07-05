"""Stage 3: consistency as a portrait axis — spread beats the mean for diagnosis.

Two different problems hide behind the same mean error:
  high spread                -> repeatability problem (mechanics inconsistent);
  low spread + high error    -> calibration problem (consistent, but aimed off
                                 the head line — e.g. a stable sideways bias).

All stats are DUEL-SCOPED (radial <= duel_hu): outside the duel window the
radial measures where enemies happened to appear, not how the player aims.
"""

import statistics
from dataclasses import dataclass
from typing import List, Sequence

from aim_metrics import DEFAULT_DUEL_HU, FrameSample

# Diagnosis thresholds (HU, duel-scoped). Validated GT clips sit around
# std 0.67-0.76 / MAE 1.34-1.39 — i.e. "consistent, calibration-limited".
DEFAULT_SPREAD_HIGH_HU = 1.0     # std above this => repeatability problem
DEFAULT_ERROR_HIGH_HU = 1.0      # duel MAE above this => calibration problem
MIN_DUEL_FRAMES = 20             # below this any verdict is a hypothesis

_DIAGNOSIS_TEXT = {
    "repeatability": "высокий разброс -> проблема ПОВТОРЯЕМОСТИ (механика нестабильна)",
    "calibration": "разброс низкий, ошибка высокая -> проблема КАЛИБРОВКИ (стабильно мимо)",
    "stable_accurate": "разброс и ошибка низкие -> стабильно и точно",
    "insufficient": "мало данных в дуэлях — гипотеза, не диагноз",
}


@dataclass(frozen=True)
class ConsistencyReport:
    duel_hu: float
    duel_frames: int
    duel_mae_hu: float       # mean radial in duel (nan if no duel frames)
    std_hu: float            # spread of radial in duel
    p95_hu: float            # tail in duel
    iqr_hu: float            # robust spread (Q3 - Q1) in duel
    diagnosis: str           # repeatability | calibration | stable_accurate | insufficient


def _classify(duel_frames: int, std_hu: float, mae_hu: float,
              spread_high_hu: float, error_high_hu: float) -> str:
    if duel_frames < MIN_DUEL_FRAMES:
        return "insufficient"
    if std_hu > spread_high_hu:
        return "repeatability"
    return "calibration" if mae_hu > error_high_hu else "stable_accurate"


def compute_consistency(samples: Sequence[FrameSample],
                        duel_hu: float = DEFAULT_DUEL_HU,
                        spread_high_hu: float = DEFAULT_SPREAD_HIGH_HU,
                        error_high_hu: float = DEFAULT_ERROR_HIGH_HU,
                        ) -> ConsistencyReport:
    radials: List[float] = [s.radial_hu for s in samples if s.radial_hu <= duel_hu]
    n = len(radials)
    if n == 0:
        nan = float("nan")
        return ConsistencyReport(duel_hu, 0, nan, nan, nan, nan, "insufficient")

    mae = statistics.fmean(radials)
    std = statistics.pstdev(radials)
    if n >= 2:
        q1, _, q3 = statistics.quantiles(radials, n=4)
        iqr = q3 - q1
    else:
        iqr = 0.0
    p95 = sorted(radials)[max(int(round(0.95 * n)) - 1, 0)]

    return ConsistencyReport(
        duel_hu=duel_hu,
        duel_frames=n,
        duel_mae_hu=mae,
        std_hu=std,
        p95_hu=p95,
        iqr_hu=iqr,
        diagnosis=_classify(n, std, mae, spread_high_hu, error_high_hu),
    )


def format_consistency(report: ConsistencyReport) -> str:
    """Done-when shape: портрет явно классифицирует «повторяемость vs калибровка»."""
    lines = [f"=== КОНСИСТЕНТНОСТЬ (дуэль <={report.duel_hu:g} HU, "
             f"{report.duel_frames} кадров) ==="]
    if report.duel_frames:
        lines.append(
            f"  Разброс: std ±{report.std_hu:.3f} HU,"
            f" IQR {report.iqr_hu:.3f} HU, p95 {report.p95_hu:.3f} HU"
            f"  (MAE {report.duel_mae_hu:.3f} HU)"
        )
    lines.append(f"  Диагноз: {_DIAGNOSIS_TEXT[report.diagnosis]}")
    return "\n".join(lines)
