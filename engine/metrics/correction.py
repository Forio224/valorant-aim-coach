"""Stage 4: correction signature — overshoot/undershoot on flick episodes.

The only "HOW" metric (mechanics, not placement): did the player swing past the
head and come back (overshoot), or stop short and re-approach (undershoot)?
Per axis and signed; ordinal frame logic, fps used only for second-based gates.

PROXY CAVEAT (amended roadmap): dx/dy are the head relative to the FIXED
crosshair, so a sign flip can also be an enemy strafing through the aim point.
Mitigations: only flick episodes where camera speed dominates
(peak_closing_speed >= MIN_FLICK_SPEED_HU_S), a deadband against detector
noise, and the analysis window capped at duel entry + settle margin.
This measures output-space correction, NOT raw mouse mechanics.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from engine.geometry import FrameSample
from engine.clip_context import ClipContext
from engine.episodes import (DEFAULT_DUEL_HU, Episode,
                             MIN_FLICK_DETECTION_DENSITY, detection_density)
from engine.input_space import cm_per_360

DEADBAND_HU = 0.3              # |offset| below this carries no sign information
MIN_FLICK_SPEED_HU_S = 20.0    # slower approaches may be enemy/strafe motion
SETTLE_S = 0.15                # window past duel entry where overshoot shows up
STALL_MIN_S = 0.08             # how long "stopped short" must last
STALL_SPEED_HU_S = 6.0         # below this per-axis speed = stalled
UNDERSHOOT_MIN_HU = 1.0        # a stall counts only meaningfully short of the head
RESUME_DROP_HU = 0.5           # closing must resume by at least this after a stall
SENS_HIGH_CM360 = 30.0   # некалибр.: быстрее ~30 см/360 сообщество зовёт высокой
SENS_LOW_CM360 = 60.0    # некалибр.: медленнее — заведомо «контрольная» сенса

_AXIS_LABELS = {"overshoot": "перелёт", "undershoot": "недолёт", "clean": "чисто"}


@dataclass(frozen=True)
class CorrectionVerdict:
    """Per-flick verdicts for both axes, with evidence frames."""
    episode_index: int          # 1-based, matches format_episodes numbering
    start_frame: int
    time_s: float
    x: str                      # "overshoot" | "undershoot" | "clean"
    x_evidence_frame: Optional[int]
    y: str
    y_evidence_frame: Optional[int]


@dataclass(frozen=True)
class CorrectionReport:
    flicks_total: int           # episodes tagged flick
    flicks_analysed: int        # subset where camera speed dominates + dense track
    flicks_sparse: int          # отсеяны гейтом плотности детекций (Фаза 4)
    x_overshoots: int
    x_undershoots: int
    y_overshoots: int
    y_undershoots: int
    symmetry_note: str
    verdicts: Tuple[CorrectionVerdict, ...]


# ── Per-axis classification (ordinal, frame-order based) ─────────────────────

def _find_stall(frames: List[int], values: List[float],
                stall_min_frames: int, stall_speed_hu_frame: float,
                ) -> Optional[Tuple[int, int, float]]:
    """Longest-first run of slow motion meaningfully short of the head.

    Returns (start_idx, end_idx, level) of the first qualifying stall, else None.
    """
    run_start: Optional[int] = None
    for i in range(1, len(values)):
        step = abs(values[i] - values[i - 1]) / (frames[i] - frames[i - 1])
        slow = step < stall_speed_hu_frame and abs(values[i]) >= UNDERSHOOT_MIN_HU
        if slow:
            if run_start is None:
                run_start = i - 1
        elif run_start is not None:
            if frames[i - 1] - frames[run_start] >= stall_min_frames:
                level = sum(abs(v) for v in values[run_start:i]) / (i - run_start)
                return run_start, i - 1, level
            run_start = None
    if run_start is not None and frames[-1] - frames[run_start] >= stall_min_frames:
        level = sum(abs(v) for v in values[run_start:]) / (len(values) - run_start)
        return run_start, len(values) - 1, level
    return None


def _classify_axis(frames: List[int], values: List[float], fps: float,
                   deadband_hu: float) -> Tuple[str, Optional[int]]:
    """Overshoot = sign flip beyond deadband; undershoot = stall then resume."""
    first = next((i for i, v in enumerate(values) if abs(v) >= deadband_hu), None)
    if first is None:
        return "clean", None
    initial_positive = values[first] > 0

    for i in range(first + 1, len(values)):
        v = values[i]
        if abs(v) >= deadband_hu and (v > 0) != initial_positive:
            return "overshoot", frames[i]

    stall = _find_stall(frames, values,
                        stall_min_frames=max(int(round(STALL_MIN_S * fps)), 2),
                        stall_speed_hu_frame=STALL_SPEED_HU_S / fps)
    if stall is not None:
        start_idx, end_idx, level = stall
        resumed = any(abs(v) <= level - RESUME_DROP_HU
                      for v in values[end_idx + 1:])
        if resumed:
            return "undershoot", frames[start_idx]
    return "clean", None


# ── Episode-level analysis ───────────────────────────────────────────────────

def _analysis_window(ep: Episode, duel_hu: float,
                     settle_frames: int) -> List[FrameSample]:
    """Birth -> duel entry + settle margin: where the correction shows up."""
    entry = next(s.frame_idx for s in ep.samples if s.radial_hu <= duel_hu)
    return [s for s in ep.samples if s.frame_idx <= entry + settle_frames]


def compute_correction(episodes: Sequence[Episode], ctx: ClipContext,
                       duel_hu: float = DEFAULT_DUEL_HU,
                       deadband_hu: float = DEADBAND_HU,
                       min_flick_speed_hu_s: float = MIN_FLICK_SPEED_HU_S,
                       min_density: float = MIN_FLICK_DETECTION_DENSITY,
                       ) -> CorrectionReport:
    settle_frames = max(int(round(SETTLE_S * ctx.fps)), 1)
    flicks_total = sum(1 for ep in episodes if ep.kind == "flick")

    verdicts: List[CorrectionVerdict] = []
    sparse = 0
    for i, ep in enumerate(episodes, start=1):
        if ep.kind != "flick" or ep.peak_closing_speed_hu_s < min_flick_speed_hu_s:
            continue
        if detection_density(ep) < min_density:
            sparse += 1            # посчитан, но исключён из вердиктов/счётчиков
            continue
        window = _analysis_window(ep, duel_hu, settle_frames)
        frames = [s.frame_idx for s in window]
        x, x_frame = _classify_axis(frames, [s.dx_hu for s in window],
                                    ctx.fps, deadband_hu)
        y, y_frame = _classify_axis(frames, [s.dy_hu for s in window],
                                    ctx.fps, deadband_hu)
        verdicts.append(CorrectionVerdict(
            episode_index=i, start_frame=ep.start_frame,
            time_s=ctx.frame_to_seconds(ep.start_frame),
            x=x, x_evidence_frame=x_frame, y=y, y_evidence_frame=y_frame,
        ))

    counts = {axis: {kind: sum(1 for v in verdicts if getattr(v, axis) == kind)
                     for kind in ("overshoot", "undershoot")}
              for axis in ("x", "y")}
    return CorrectionReport(
        flicks_total=flicks_total,
        flicks_analysed=len(verdicts),
        flicks_sparse=sparse,
        x_overshoots=counts["x"]["overshoot"],
        x_undershoots=counts["x"]["undershoot"],
        y_overshoots=counts["y"]["overshoot"],
        y_undershoots=counts["y"]["undershoot"],
        symmetry_note=_symmetry_note(len(verdicts), counts, cm_per_360(ctx.edpi)),
        verdicts=tuple(verdicts),
    )


def _symmetry_note(analysed: int, counts: dict,
                   cm360: Optional[float] = None) -> str:
    """Symmetric axis overshoot smells like sens; asymmetric — muscle memory.

    Фаза 4: при известной cm/360 сенса-гипотеза смотрит на реальную сенсу
    (язык всюду гипотезный — нота, не вердикт)."""
    if analysed < 3:
        return f"мало флик-эпизодов ({analysed}) — сигнатура = гипотеза, не диагноз"
    rate_x = counts["x"]["overshoot"] / analysed
    rate_y = counts["y"]["overshoot"] / analysed
    if rate_x == 0 and rate_y == 0:
        return "перелётов нет — коррекция дисциплинированная"
    if abs(rate_x - rate_y) <= 0.25:
        if cm360 is not None and cm360 <= SENS_HIGH_CM360:
            return (f"перелёт симметричен по осям — и сенса высокая"
                    f" ({cm360:.1f} см/360): сенса-подобная гипотеза усиливается")
        if cm360 is not None:
            return (f"перелёт симметричен по осям — но сенса умеренная"
                    f" ({cm360:.1f} см/360): смотри в сторону доводки/мышечной"
                    f" памяти")
        return "перелёт симметричен по осям — похоже на сенсу (сенса-подобное)"
    return "перелёт асимметричен по осям — похоже на мышечную память/доводку"


# ── Human-readable report ────────────────────────────────────────────────────

def _axis_cell(kind: str, evidence_frame: Optional[int]) -> str:
    label = _AXIS_LABELS[kind]
    return f"{label} (кадр {evidence_frame})" if evidence_frame is not None else label


def format_correction(report: CorrectionReport, ctx: ClipContext) -> str:
    n = report.flicks_analysed
    lines = [
        "=== СИГНАТУРА КОРРЕКЦИИ (flick-эпизоды) ===",
        f"  Флик-эпизодов: {report.flicks_total}, камера доминирует: {n}",
        f"  X: перелёт {report.x_overshoots}, недолёт {report.x_undershoots},"
        f" чисто {n - report.x_overshoots - report.x_undershoots}",
        f"  Y: перелёт {report.y_overshoots}, недолёт {report.y_undershoots},"
        f" чисто {n - report.y_overshoots - report.y_undershoots}",
        f"  Вывод: {report.symmetry_note}",
    ]
    for v in report.verdicts:
        lines.append(
            f"  #{v.episode_index:<2} старт кадр {v.start_frame} ({v.time_s:.2f} c):"
            f"  X={_axis_cell(v.x, v.x_evidence_frame)},"
            f"  Y={_axis_cell(v.y, v.y_evidence_frame)}"
        )
    lines.append("  Замечание: смена знака может быть стрейфом врага — это"
                 " ПРОКСИ-метрика по output-space, не механика мыши.")
    return "\n".join(lines)
