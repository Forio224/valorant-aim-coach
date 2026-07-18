# -*- coding: utf-8 -*-
"""Stage 5 (Фаза 2A): фаз-метрики флика — разложение наведения на баллистику
и доводку.

Обогащает correction: было «итог» (перелёт/недолёт), стало «+ как флик пришёл».
Каждый флик режется по ряду offset(t)=radial_hu на баллистику (старт → первый
вход в near-band) и settle (вход → стабилизация). Четыре метрики (все считает
движок): overshoot (истинный перелёт через центр по знаковым осям), settle_time
(скорость доводки), settle_jitter (рывковость по производной), correction_path
(суммарный путь доводки = эффективность).

Кавеат наследуется от correction: output-space прокси; граница фаз и конец
settle — эвристика (выстрела в данных нет), не механика мыши.
"""
from dataclasses import dataclass
from statistics import median, pstdev
from typing import List, Optional, Sequence, Tuple

from engine.clip_context import ClipContext
from engine.episodes import (Episode, MIN_FLICK_DETECTION_DENSITY,
                             detection_density)
from engine.metrics.correction import DEADBAND_HU, MIN_FLICK_SPEED_HU_S

NEAR_BAND_HU = 0.8            # граница баллистика↔settle (вход в band)
SETTLE_TOL_HU = 0.35         # тесный допуск «на цели»
SETTLE_STABLE_FRAMES = 3     # K: сколько кадров держать допуск = «успокоился»
MIN_FLICKS_FOR_PHASE = 3     # порог confidence фаз


@dataclass(frozen=True)
class FlickPhase:
    """Пофликовая запись (usable = arrived and settled; иначе метрики = None)."""
    episode_index: int          # 1-based, как в format_episodes/correction
    start_frame: int
    arrived: bool
    settled: bool
    flick_overshoot_hu: Optional[float]
    settle_time_frames: Optional[int]
    settle_jitter_hu: Optional[float]
    correction_path_hu: Optional[float]
    overshoot_evidence_frame: Optional[int]


@dataclass(frozen=True)
class FlickPhaseReport:
    flicks_analysed: int         # прошли гейт флика (kind + скорость + плотность)
    flicks_sparse: int           # отсеяны гейтом плотности (посчитаны, не судимы)
    flicks_arrived: int          # вошли в near-band
    flicks_settled: int          # = usable (участвуют в медианах)
    flicks_jitter_n: int         # settled-флики, реально давшие jitter (не None)
    flick_overshoot_hu_median: Optional[float]
    settle_time_frames_median: Optional[float]
    settle_jitter_hu_median: Optional[float]
    correction_path_hu_median: Optional[float]
    phase_confidence: str        # diagnosis | hypothesis | insufficient
    phases: Tuple[FlickPhase, ...]


def _ballistic_entry(radials: Sequence[float], near_band_hu: float) -> Optional[int]:
    """Первый индекс входа в near-band (конец баллистики / начало settle)."""
    return next((i for i, r in enumerate(radials) if r <= near_band_hu), None)


def _settle_index(frames: Sequence[int], radials: Sequence[float], b: int,
                  tol: float, k: int) -> Optional[int]:
    """Первый индекс устойчивого прогона в КАДРОВОМ пространстве.

    Прогон продолжается только по кадрово-смежным сэмплам (frame ровно +1);
    разрыв кадра начинает прогон заново (Фаза 4: на дырявом YOLO-треке «3 подряд
    сэмпла» иначе растягиваются на 15 кадров — ложное «оселся»). Квалификация —
    прогон покрывает >= k подряд идущих кадров.
    """
    run_start: Optional[int] = None
    for j in range(b, len(radials)):
        if radials[j] > tol:
            run_start = None
            continue
        if run_start is None or frames[j] != frames[j - 1] + 1:
            run_start = j                      # разрыв кадра = новый прогон
        if frames[j] - frames[run_start] + 1 >= k:
            return run_start
    return None


def _axis_overshoot(values: Sequence[float],
                    deadband: float) -> Tuple[float, Optional[int]]:
    """Истинный перелёт по знаковой оси: величина захода за центр после смены
    знака. (0, None), если ось не пересекает центр за deadband."""
    first = next((i for i, v in enumerate(values) if abs(v) >= deadband), None)
    if first is None:
        return 0.0, None
    initial_positive = values[first] > 0
    for i in range(first + 1, len(values)):
        if abs(values[i]) >= deadband and (values[i] > 0) != initial_positive:
            opp = [(abs(values[j]), j) for j in range(i, len(values))
                   if (values[j] > 0) != initial_positive]
            mag, idx = max(opp)
            return mag, idx
    return 0.0, None


def _usable_phase(ep: Episode, index: int, near_band_hu: float, settle_tol_hu: float,
                  stable_frames: int, deadband_hu: float) -> FlickPhase:
    """Разложение одного (уже прошедшего гейт) флика на фазы + метрики."""
    frames = [s.frame_idx for s in ep.samples]
    radials = [s.radial_hu for s in ep.samples]
    b = _ballistic_entry(radials, near_band_hu)
    if b is None:
        return FlickPhase(index, ep.start_frame, False, False,
                          None, None, None, None, None)
    s = _settle_index(frames, radials, b, settle_tol_hu, stable_frames)
    if s is None:
        return FlickPhase(index, ep.start_frame, True, False,
                          None, None, None, None, None)

    over_x, ix = _axis_overshoot([smp.dx_hu for smp in ep.samples[:s + 1]],
                                 deadband_hu)
    over_y, iy = _axis_overshoot([smp.dy_hu for smp in ep.samples[:s + 1]],
                                 deadband_hu)
    # берём ось с бОльшим перелётом; при точном равенстве — X (произвольно, но
    # детерминированно; направление всё равно уточняют булевы correction.x/y)
    overshoot, ev_local = (over_y, iy) if over_y > over_x else (over_x, ix)
    ev_frame = frames[ev_local] if ev_local is not None else None

    seg_frames = frames[b:s + 1]
    seg = radials[b:s + 1]
    # jitter — только кадрово-смежные дельты: дельта через дырку = склейка двух
    # движений, завышала pstdev на ровном месте. < 2 смежных пар -> None.
    adjacent = [seg[j] - seg[j - 1] for j in range(1, len(seg))
                if seg_frames[j] == seg_frames[j - 1] + 1]
    jitter = round(pstdev(adjacent), 3) if len(adjacent) >= 2 else None
    # путь остаётся суммой |Δ| по всем сэмплам — при дырках это нижняя оценка
    path = sum(abs(seg[j] - seg[j - 1]) for j in range(1, len(seg)))
    return FlickPhase(
        episode_index=index, start_frame=ep.start_frame,
        arrived=True, settled=True,
        flick_overshoot_hu=round(overshoot, 3),
        settle_time_frames=frames[s] - frames[b],
        settle_jitter_hu=jitter,
        correction_path_hu=round(path, 3),
        overshoot_evidence_frame=ev_frame,
    )


def compute_flick_phases(episodes: Sequence[Episode], ctx: ClipContext,
                         near_band_hu: float = NEAR_BAND_HU,
                         settle_tol_hu: float = SETTLE_TOL_HU,
                         stable_frames: int = SETTLE_STABLE_FRAMES,
                         deadband_hu: float = DEADBAND_HU,
                         min_flick_speed_hu_s: float = MIN_FLICK_SPEED_HU_S,
                         min_density: float = MIN_FLICK_DETECTION_DENSITY,
                         ) -> FlickPhaseReport:
    phases: List[FlickPhase] = []
    sparse = 0
    for i, ep in enumerate(episodes, start=1):
        if ep.kind != "flick" or ep.peak_closing_speed_hu_s < min_flick_speed_hu_s:
            continue
        if detection_density(ep) < min_density:
            sparse += 1            # посчитан, но исключён из вердиктов/медиан
            continue
        phases.append(_usable_phase(ep, i, near_band_hu, settle_tol_hu,
                                    stable_frames, deadband_hu))

    usable = [p for p in phases if p.settled]

    def _med(attr: str) -> Optional[float]:
        vals = [getattr(p, attr) for p in usable
                if getattr(p, attr) is not None]
        return round(median(vals), 3) if vals else None

    jitter_vals = [p.settle_jitter_hu for p in usable
                   if p.settle_jitter_hu is not None]
    # медиана рывковости молчит, пока фликов с честным jitter меньше порога —
    # иначе confidence по settled дал бы утвердительный язык про 1 флик
    jitter_median = (round(median(jitter_vals), 3)
                     if len(jitter_vals) >= MIN_FLICKS_FOR_PHASE else None)

    if not usable:
        conf = "insufficient"
    elif len(usable) >= MIN_FLICKS_FOR_PHASE:
        conf = "diagnosis"
    else:
        conf = "hypothesis"

    return FlickPhaseReport(
        flicks_analysed=len(phases),
        flicks_sparse=sparse,
        flicks_arrived=sum(1 for p in phases if p.arrived),
        flicks_settled=len(usable),
        flicks_jitter_n=len(jitter_vals),
        flick_overshoot_hu_median=_med("flick_overshoot_hu"),
        settle_time_frames_median=(round(median([p.settle_time_frames
                                                  for p in usable]), 3)
                                   if usable else None),
        settle_jitter_hu_median=jitter_median,
        correction_path_hu_median=_med("correction_path_hu"),
        phase_confidence=conf,
        phases=tuple(phases),
    )


def format_flick_phases(report: FlickPhaseReport, ctx: ClipContext) -> str:
    """Человеко-читаемое разложение (CLI), рядом с format_correction."""
    r = report
    ms = (None if r.settle_time_frames_median is None
          else round(1000 * r.settle_time_frames_median / ctx.fps))
    lines = [
        "=== ФАЗЫ ФЛИКА (баллистика → доводка) ===",
        f"  Фликов: анализ {r.flicks_analysed}, дошли {r.flicks_arrived},"
        f" оселись {r.flicks_settled}  [{r.phase_confidence}]",
        f"  Перелёт (медиана): {r.flick_overshoot_hu_median} HU",
        f"  Доводка (медиана): {r.settle_time_frames_median} кадр"
        f" ({ms} мс)",
        f"  Рывковость (медиана): {r.settle_jitter_hu_median} HU",
        f"  Путь доводки (медиана): {r.correction_path_hu_median} HU",
    ]
    for p in r.phases:
        if not p.settled:
            state = "не дошёл" if not p.arrived else "не оселся"
            lines.append(f"  #{p.episode_index:<2} старт {p.start_frame}: {state}")
            continue
        lines.append(
            f"  #{p.episode_index:<2} старт {p.start_frame}:"
            f"  перелёт {p.flick_overshoot_hu} HU,"
            f"  доводка {p.settle_time_frames} к,"
            f"  рывк {p.settle_jitter_hu},"
            f"  путь {p.correction_path_hu} HU")
    lines.append("  Кавеат: output-space прокси; конец settle — стабилизация"
                 " траектории, не реальный выстрел; путь — нижняя оценка при"
                 " пропусках детекции.")
    return "\n".join(lines)
