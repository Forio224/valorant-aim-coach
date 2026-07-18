r"""
engine/geometry.py
==================
Ядро геометрии аим-паспорта (Phase A): типы цели/сэмпла и чистые функции
нормировки в Head Units. Перенесено ВЕРБАТИМ из `aim_metrics.py` (Фаза 3,
Task 1) — ни один литерал/формула не меняется; `aim_metrics` реэкспортирует эти
имена, чтобы существующие импорты и тесты не сломались.

Прицел зафиксирован в центре экрана (Valorant держит его там); все смещения
нормируются на высоту головы цели (HU = высота её бокса), поэтому дистанция до
врага сокращается. Модуль сознательно НЕ зависит от источников кадров и от
`ClipContext` — это чистое ядро, на которое опираются модули `engine/`.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


# ── Defaults ──────────────────────────────────────────────────────────────────────

DEFAULT_DUEL_HU = 3.0          # head within this many HU of centre => "active duel"
MIN_HEAD_PX = 1.0              # guard against /0 when a head box has zero height


# ── Data contracts ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Head:
    """Minimal target description usable from either source."""
    cx: float
    cy: float
    height_px: float


@dataclass(frozen=True)
class FrameSample:
    """One measured frame: signed HU offsets of the target head from crosshair."""
    frame_idx: int
    dx_hu: float          # + right of crosshair
    dy_hu: float          # - above crosshair (aim too low)
    radial_hu: float      # hypot(dx, dy) = absolute aim error this frame
    head_height_px: float


# ── Core geometry ──────────────────────────────────────────────────────────────────

def pick_target(heads: List[Head], crosshair: Tuple[float, float]) -> Optional[Head]:
    """The enemy the player is engaging = the head nearest the crosshair."""
    if not heads:
        return None
    cx, cy = crosshair
    return min(heads, key=lambda h: float(np.hypot(h.cx - cx, h.cy - cy)))


def sample_frame(frame_idx: int, head: Head,
                 crosshair: Tuple[float, float]) -> FrameSample:
    """Convert a target head + crosshair into a normalised HU offset sample."""
    cx, cy = crosshair
    hu = max(head.height_px, MIN_HEAD_PX)
    dx = (head.cx - cx) / hu
    dy = (head.cy - cy) / hu
    return FrameSample(
        frame_idx=frame_idx,
        dx_hu=dx,
        dy_hu=dy,
        radial_hu=float(np.hypot(dx, dy)),
        head_height_px=head.height_px,
    )


# ── Aggregation ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AimPassport:
    frames_measured: int          # frames with a usable target head
    duel_frames: int              # subset within DUEL_HU of centre
    duel_hu: float

    overall_mae_hu: float         # mean radial over ALL measured frames
    duel_mae_hu: float            # mean radial over active-duel frames (nan if none)

    # Bias / stability are DUEL-SCOPED: over all frames they measure where enemies
    # happened to appear (screen-edge geometry), not how the player aims. Inside
    # the duel window they isolate actual aiming behaviour.
    y_bias_hu: float              # signed mean dy in-duel (<0 => aim too low / lazy)
    x_bias_hu: float              # signed mean dx in-duel
    x_abs_hu: float               # mean |dx| in-duel (horizontal micro-correction)
    y_abs_hu: float               # mean |dy| in-duel

    tracking_std_hu: float        # std of radial in-duel (stability on target)
    median_hu: float              # median radial over ALL frames (distribution)
    p95_hu: float                 # 95th pct radial over ALL frames (tail)


def _safe_mean(a: np.ndarray) -> float:
    return float(np.mean(a)) if a.size else float("nan")


def _safe_std(a: np.ndarray) -> float:
    return float(np.std(a)) if a.size else float("nan")


def compute_passport(samples: List[FrameSample],
                     duel_hu: float = DEFAULT_DUEL_HU) -> AimPassport:
    if not samples:
        return AimPassport(0, 0, duel_hu, *[float("nan")] * 9)

    dx = np.array([s.dx_hu for s in samples])
    dy = np.array([s.dy_hu for s in samples])
    radial = np.array([s.radial_hu for s in samples])
    duel = radial <= duel_hu          # active-engagement frames

    return AimPassport(
        frames_measured=len(samples),
        duel_frames=int(duel.sum()),
        duel_hu=duel_hu,
        overall_mae_hu=float(np.mean(radial)),
        duel_mae_hu=_safe_mean(radial[duel]),
        y_bias_hu=_safe_mean(dy[duel]),
        x_bias_hu=_safe_mean(dx[duel]),
        x_abs_hu=_safe_mean(np.abs(dx[duel])),
        y_abs_hu=_safe_mean(np.abs(dy[duel])),
        tracking_std_hu=_safe_std(radial[duel]),
        median_hu=float(np.median(radial)),
        p95_hu=float(np.percentile(radial, 95)),
    )
