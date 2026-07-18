"""Слой атрибуции цели по намерению (Фаза 3, Компонент 1 спеки 2026-07-15).

Проблема (дефект A1): `consistency`/`bias` считались по потоку кадров без
идентичности — «ближайшая к центру голова» бралась независимо на каждом кадре,
и смена врага под прицелом влетала в разброс механики игрока. «Ближайшая» —
плохой прокси для «та, которую игрок ведёт»: он разваливается там, где игрок
действует осознанно (заход в спину, мультикилл, выбор сложной цели).

Решение: между `segment_episodes` и метриками встаёт `attribute_targets` —
оценивает движение камеры по медиане смещений голов, из неё считает НАМЕРЕНИЕ
(насколько КАМЕРА закрывает дистанцию до головы, без собственного движения
врага), и по правилу выбора с гистерезисом назначает один трек на кадр. Спорные
кадры честно помечаются `contested` и из механики исключаются, но считаются.

Свойство, которое сохраняем: работаем по детекциям, БЕЗ декодирования видео —
пиксельные позиции голов восстанавливаются из HU-сэмплов эпизодов.

Все пороги НЕКАЛИБРОВАННЫЕ (калибровка на реальных клипах — отдельная задача,
как conf=0.4 на холдауте); в секундах / HU-в-секунду, чтобы 30 и 60 fps
оставались сравнимыми.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Dict, List, Optional, Sequence, Set, Tuple

from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.geometry import DEFAULT_DUEL_HU, MIN_HEAD_PX, FrameSample

# ── Ручки (некалибр.; спека §Ручки — в секундах / HU-в-секунду) ───────────────

INTENT_WINDOW_S = 0.05        # некалибр. ~3 кадра при 60 fps: гасит одиночный шум
MIN_INTENT_HU_S = 8.0         # некалибр. ниже — шум оценки камеры
SWITCH_MARGIN_HU_S = 6.0      # некалибр. запас, при котором кандидат явно опережает
CONTESTED_MARGIN_HU_S = 3.0   # некалибр. ближе — движок признаёт спор, не решает
DWELL_MAX_CAMERA_HU_S = 4.0   # некалибр. «камера почти стоит» = удержание


# ── Контракты (спека §Контракты — вербатим) ──────────────────────────────────

@dataclass(frozen=True)
class AttributedSample:
    frame_idx: int
    track_id: Optional[int]        # None = contested
    dx_hu: float
    dy_hu: float
    radial_hu: float
    head_height_px: float
    switch: bool                   # первый кадр новой цели
    contested: bool


@dataclass(frozen=True)
class TargetChoice:
    track_id: int
    from_frame: int
    to_frame: int
    chosen_at_radial_hu: float          # как далеко была цель в момент выбора
    head_height_px: float               # прокси дистанции
    lateral_speed_hu_s: float           # прокси стрейфа (по residual, не камере)
    switch_cost_frames: Optional[int]   # кадров от переключения до входа в дуэль


@dataclass(frozen=True)
class AttributionResult:
    samples: Tuple[AttributedSample, ...]
    choices: Tuple[TargetChoice, ...]
    switches: int
    contested_frames: int
    camera_confidence: str              # diagnosis | hypothesis | insufficient


# ── Внутренние помощники ──────────────────────────────────────────────────────

Vec = Tuple[float, float]


def _head_px(s: FrameSample, crosshair: Vec) -> Vec:
    """Восстановить пиксельную позицию головы из HU-сэмпла (инверсия sample_frame)."""
    hu = max(s.head_height_px, MIN_HEAD_PX)
    return (crosshair[0] + s.dx_hu * hu, crosshair[1] + s.dy_hu * hu)


def _mag(v: Vec) -> float:
    return math.hypot(v[0], v[1])


def _camera_shift(prev: Dict[int, FrameSample], cur: Dict[int, FrameSample],
                  crosshair: Vec) -> Optional[Vec]:
    """Медиана смещений голов, живых и на N, и на N−1 (медиана — чтобы один
    стрейфер не утащил оценку). None = оценить нельзя (< 2 общих треков): при
    одном общем треке его собственный стрейф протёк бы в «камеру» на 100%."""
    common = set(prev) & set(cur)
    if len(common) < 2:
        return None
    dxs, dys = [], []
    for t in common:
        p0 = _head_px(prev[t], crosshair)
        p1 = _head_px(cur[t], crosshair)
        dxs.append(p1[0] - p0[0])
        dys.append(p1[1] - p0[1])
    return (median(dxs), median(dys))


def _intent_hu_s(s: FrameSample, camera: Vec, crosshair: Vec, fps: float) -> float:
    """HU/с дистанции, закрытых КАМЕРОЙ к этой голове (>0 = прицел ведётся к ней).

    Статичный в мире враг смещается на экране ровно на `camera`; его позиция на
    N−1 (относительно центра) = p − camera. Закрытие камерой = |p−camera| − |p|
    (дистанция на N−1 минус на N). Собственное движение врага в оценку не входит.
    """
    hu = max(s.head_height_px, MIN_HEAD_PX)
    px, py = _head_px(s, crosshair)
    p = (px - crosshair[0], py - crosshair[1])
    dist_now = _mag(p)
    dist_prev = _mag((p[0] - camera[0], p[1] - camera[1]))
    return (dist_prev - dist_now) / hu * fps


def _nearest_track(heads: Dict[int, FrameSample]) -> int:
    """Ближайшая к центру голова; тай-брейк по track_id (детерминизм)."""
    return min(heads, key=lambda t: (heads[t].radial_hu, t))


def _confidence_for(peak_heads: int) -> str:
    if peak_heads >= 3:
        return "diagnosis"
    if peak_heads == 2:
        return "hypothesis"
    return "insufficient"


# ── Основной проход ───────────────────────────────────────────────────────────

def attribute_targets(episodes: Sequence[Episode], ctx: ClipContext,
                      duel_hu: float = DEFAULT_DUEL_HU) -> AttributionResult:
    crosshair = ctx.crosshair
    fps = ctx.fps

    # frame_idx -> {track_id: FrameSample}
    frames: Dict[int, Dict[int, FrameSample]] = {}
    for ep in episodes:
        for s in ep.samples:
            frames.setdefault(s.frame_idx, {})[ep.track_id] = s
    if not frames:
        return AttributionResult((), (), 0, 0, "insufficient")

    order = sorted(frames)
    window = max(int(round(INTENT_WINDOW_S * fps)), 1)
    peak_heads = max(len(frames[f]) for f in order)

    # Трек «жив» на каждом кадре своего эпизода — включая внутренние детекторные
    # разрывы, которые episodes_from_tracks мостит (gap ≤ gap_tolerance). Нужно,
    # чтобы удерживать цель сквозь короткую окклюзию, а не считать её ушедшей.
    alive_at: Dict[int, Set[int]] = defaultdict(set)
    for ep in episodes:
        for fr in range(ep.start_frame, ep.end_frame + 1):
            alive_at[fr].add(ep.track_id)

    # Мгновенное намерение по кадрам (камера оценима) + сама камера на кадр.
    cameras: Dict[int, Optional[Vec]] = {}
    inst: Dict[int, Dict[int, float]] = {}
    for f in order:
        cam = _camera_shift(frames.get(f - 1, {}), frames[f], crosshair)
        cameras[f] = cam
        if cam is not None:
            inst[f] = {t: _intent_hu_s(s, cam, crosshair, fps)
                       for t, s in frames[f].items()}

    def acc_intent(f: int, t: int) -> Optional[float]:
        """Среднее мгновенное намерение по окну (HU/с). None = нет камерных данных."""
        vals = [inst[g][t] for g in range(f - window + 1, f + 1)
                if g in inst and t in inst[g]]
        return sum(vals) / len(vals) if vals else None

    samples_out: List[AttributedSample] = []
    choices_out: List[TargetChoice] = []
    current: Optional[int] = None
    open_choice: Optional[dict] = None
    switches = 0
    contested_frames = 0

    def close_choice(to_frame: int) -> None:
        nonlocal open_choice
        if open_choice is None:
            return
        laterals = open_choice["laterals"]
        lateral_speed = sum(laterals) / len(laterals) if laterals else 0.0
        choices_out.append(TargetChoice(
            track_id=open_choice["track_id"],
            from_frame=open_choice["from_frame"],
            to_frame=to_frame,
            chosen_at_radial_hu=open_choice["chosen_at_radial_hu"],
            head_height_px=open_choice["head_height_px"],
            lateral_speed_hu_s=lateral_speed,
            switch_cost_frames=open_choice["switch_cost"],
        ))
        open_choice = None

    for f in order:
        heads = frames[f]
        cam = cameras[f]
        n = len(heads)
        prev_current = current
        contested = False
        chosen: Optional[int] = None

        cur_visible = current is not None and current in heads
        if (current is not None and not cur_visible
                and current in alive_at.get(f, ())):
            # Цель окклюдирована внутри своего эпизода (детекторный разрыв):
            # держим её сквозь разрыв, кадр не измеряем, чужую голову не крадём.
            continue

        if cur_visible:
            # Видимую цель держим, пока другой не опередит на SWITCH_MARGIN.
            cur_i = acc_intent(f, current) or 0.0
            others = [(acc_intent(f, t) or 0.0, t) for t in heads if t != current]
            if others:
                best_i, best_t = max(others)
                chosen = best_t if best_i - cur_i >= SWITCH_MARGIN_HU_S else current
            else:
                chosen = current
        elif cam is None and n >= 2:
            contested = True                     # камеру не оценить при 2+ головах
        elif n == 1:
            chosen = next(iter(heads))           # одна голова — она и есть цель
        else:
            vals = {t: (acc_intent(f, t) or 0.0) for t in heads}
            top_t = max(vals, key=lambda t: (vals[t], -t))
            top_v = vals[top_t]
            ordered = sorted(vals.values())
            second_v = ordered[-2] if len(ordered) >= 2 else float("-inf")
            if top_v > MIN_INTENT_HU_S:
                if top_v - second_v <= CONTESTED_MARGIN_HU_S:
                    contested = True             # два кандидата в пределах спора
                else:
                    chosen = top_t
            else:
                chosen = _nearest_track(heads)   # камера стоит → ближайшая

        if contested:
            contested_frames += 1
            if current is not None:              # цель потеряна
                close_choice(prev_frame_for(order, f))
                current = None
            near = heads[_nearest_track(heads)]
            samples_out.append(AttributedSample(
                frame_idx=f, track_id=None,
                dx_hu=near.dx_hu, dy_hu=near.dy_hu, radial_hu=near.radial_hu,
                head_height_px=near.head_height_px, switch=False, contested=True))
            continue

        assert chosen is not None
        s = heads[chosen]
        is_new = chosen != prev_current
        # Переключение-нестабильность считаем ТОЛЬКО когда уходим с ещё видимой
        # цели (осознанная смена). Вынужденная переатрибуция после ухода старой
        # цели или первичный захват — не переключение.
        switch = is_new and cur_visible
        if switch:
            switches += 1

        if is_new:
            close_choice(prev_frame_for(order, f))
            open_choice = {
                "track_id": chosen, "from_frame": f,
                "chosen_at_radial_hu": s.radial_hu,
                "head_height_px": s.head_height_px,
                "switch_cost": (0 if s.radial_hu <= duel_hu else None),
                "laterals": [],
            }
        else:
            # копим стоимость переключения (первый вход в дуэль) и боковой residual
            if open_choice is not None:
                if open_choice["switch_cost"] is None and s.radial_hu <= duel_hu:
                    open_choice["switch_cost"] = f - open_choice["from_frame"]
                lat = _lateral_residual(frames, f, chosen, cam, crosshair, fps)
                if lat is not None:
                    open_choice["laterals"].append(lat)

        current = chosen
        samples_out.append(AttributedSample(
            frame_idx=f, track_id=chosen,
            dx_hu=s.dx_hu, dy_hu=s.dy_hu, radial_hu=s.radial_hu,
            head_height_px=s.head_height_px, switch=switch, contested=False))

    close_choice(order[-1])

    return AttributionResult(
        samples=tuple(samples_out),
        choices=tuple(choices_out),
        switches=switches,
        contested_frames=contested_frames,
        camera_confidence=_confidence_for(peak_heads),
    )


def prev_frame_for(order: Sequence[int], f: int) -> int:
    """Последний обработанный кадр до f (для закрытия выбора в конце)."""
    idx = order.index(f)
    return order[idx - 1] if idx > 0 else f


def _lateral_residual(frames: Dict[int, Dict[int, FrameSample]], f: int,
                      track_id: int, camera: Optional[Vec], crosshair: Vec,
                      fps: float) -> Optional[float]:
    """Боковая (перпендикулярная лучу к центру) скорость СОБСТВЕННОГО движения
    врага, HU/с: смещение головы минус камера, спроецированное поперёк. Прокси
    стрейфа — по residual, не по камере."""
    prev = frames.get(f - 1)
    if prev is None or track_id not in prev or camera is None:
        return None
    s_prev, s_cur = prev[track_id], frames[f][track_id]
    p0 = _head_px(s_prev, crosshair)
    p1 = _head_px(s_cur, crosshair)
    residual = (p1[0] - p0[0] - camera[0], p1[1] - p0[1] - camera[1])
    p = (p1[0] - crosshair[0], p1[1] - crosshair[1])
    r = _mag(p)
    hu = max(s_cur.head_height_px, MIN_HEAD_PX)
    if r == 0:
        return _mag(residual) / hu * fps
    # перпендикулярная лучу компонента через векторное произведение
    cross = abs(residual[0] * p[1] - residual[1] * p[0]) / r
    return cross / hu * fps
