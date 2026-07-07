# -*- coding: utf-8 -*-
"""Тесты фаз-метрик флика (Фаза 2A): сегментация + четыре метрики + честность."""
from typing import List, Sequence, Tuple

from aim_metrics import FrameSample
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.metrics.flick_phase import (FlickPhaseReport, MIN_FLICKS_FOR_PHASE,
                                        compute_flick_phases, format_flick_phases)


def _ctx(fps: float = 60.0) -> ClipContext:
    return ClipContext(player_id="p", clip_id="c", fps=fps,
                       width=1920, height=1080, frame_count=10000)


def _flick(offsets: Sequence[Tuple[float, float]], start: int = 100,
           kind: str = "flick", speed: float = 50.0,
           track_id: int = 1) -> Episode:
    """Синтетический эпизод из ряда (dx_hu, dy_hu); radial = hypot."""
    samples = tuple(
        FrameSample(frame_idx=start + i, dx_hu=dx, dy_hu=dy,
                    radial_hu=(dx * dx + dy * dy) ** 0.5, head_height_px=63.0)
        for i, (dx, dy) in enumerate(offsets))
    return Episode(track_id=track_id, start_frame=start,
                   end_frame=start + len(offsets) - 1, samples=samples,
                   kind=kind, distance_bucket="mid", multi_enemy=False,
                   multi_from_frame=None, duel_frames=0,
                   peak_closing_speed_hu_s=speed)


# радиальные ряды по оси X (dy=0), чтобы radial == |dx|
def _x(radials: Sequence[float]) -> List[Tuple[float, float]]:
    return [(r, 0.0) for r in radials]


# ---- гейт флика ----------------------------------------------------------

def test_non_flick_episodes_ignored():
    eps = [_flick(_x([3, 0.6, 0.3, 0.3, 0.3]), kind="hold"),
           _flick(_x([3, 0.6, 0.3, 0.3, 0.3]), speed=5.0)]  # медленный
    rep = compute_flick_phases(eps, _ctx())
    assert rep.flicks_analysed == 0
    assert rep.phase_confidence == "insufficient"


# ---- сегментация: arrived / settled --------------------------------------

def test_not_arrived_excluded():
    # offset никогда не входит в near-band (0.8)
    rep = compute_flick_phases([_flick(_x([3, 2, 1.5, 1.2, 1.0, 0.9]))], _ctx())
    assert rep.flicks_analysed == 1 and rep.flicks_arrived == 0
    assert rep.flicks_settled == 0
    assert rep.phases[0].arrived is False and rep.phases[0].settled is False
    assert rep.settle_time_frames_median is None


def test_arrived_but_not_settled_excluded():
    # входит в band, но нет 3 подряд <= 0.35
    rep = compute_flick_phases([_flick(_x([3, 0.7, 0.3, 0.5, 0.3, 0.5, 0.3]))],
                               _ctx())
    p = rep.phases[0]
    assert p.arrived is True and p.settled is False
    assert p.settle_time_frames is None
    assert rep.flicks_arrived == 1 and rep.flicks_settled == 0


# ---- settle_time ---------------------------------------------------------

def test_settle_time_frames_and_ms():
    # b на index2 (0.6<=0.8); стабильно (<=0.35) с index5..7 → s=index5
    rep = compute_flick_phases(
        [_flick(_x([3, 1, 0.6, 0.4, 0.4, 0.3, 0.3, 0.3]), start=100)], _ctx(60))
    p = rep.phases[0]
    assert p.settled is True
    assert p.settle_time_frames == 3          # кадр105 − кадр102
    assert rep.settle_time_frames_median == 3


# ---- flick_overshoot_hu: истинный перелёт через центр ---------------------

def test_true_overshoot_measured_on_axis_crossing():
    # dx пересекает центр: +...+ затем -0.6 → перелёт 0.6
    offs = [(3, 0), (1.5, 0), (0.5, 0), (-0.6, 0), (-0.4, 0),
            (-0.2, 0), (-0.1, 0), (-0.1, 0)]
    rep = compute_flick_phases([_flick(offs, start=100)], _ctx())
    p = rep.phases[0]
    assert p.settled is True
    assert p.flick_overshoot_hu == 0.6
    assert p.overshoot_evidence_frame == 103   # кадр смены знака (пик)


def test_jitter_near_target_is_not_overshoot():
    # микродрожь у цели БЕЗ смены знака → overshoot 0 (регрессия старой формулы)
    rep = compute_flick_phases(
        [_flick(_x([3, 1, 0.3, 0.2, 0.4, 0.3, 0.3, 0.3]))], _ctx())
    assert rep.phases[0].flick_overshoot_hu == 0.0
    assert rep.phases[0].overshoot_evidence_frame is None


# ---- settle_jitter_hu по производной -------------------------------------

def test_jitter_uses_derivative_not_spread():
    smooth = _flick(_x([3, 1, 0.6, 0.5, 0.4, 0.3, 0.3, 0.3]))
    jerky = _flick(_x([3, 1, 0.6, 0.1, 0.5, 0.05, 0.3, 0.3, 0.3]))
    j_smooth = compute_flick_phases([smooth], _ctx()).phases[0].settle_jitter_hu
    j_jerky = compute_flick_phases([jerky], _ctx()).phases[0].settle_jitter_hu
    assert j_jerky > j_smooth


# ---- correction_path_hu --------------------------------------------------

def test_correction_path_sums_absolute_travel():
    # settle-сегмент [b..s]: b=index2 (0.6), s=index5 (три 0.3 подряд с index5)
    # radial: 0.6,0.4,0.4,0.3,0.3,0.3 → путь = |.4-.6|+|.4-.4|+|.3-.4|+... по [b..s]
    rep = compute_flick_phases(
        [_flick(_x([3, 1, 0.6, 0.4, 0.4, 0.3, 0.3, 0.3]))], _ctx())
    # [b..s] = index2..5 = 0.6,0.4,0.4,0.3 → пути 0.2+0.0+0.1 = 0.3
    assert rep.phases[0].correction_path_hu == 0.3


# ---- confidence ----------------------------------------------------------

def test_confidence_thresholds():
    good = _x([3, 1, 0.6, 0.3, 0.3, 0.3])   # usable-флик
    assert compute_flick_phases([], _ctx()).phase_confidence == "insufficient"
    two = compute_flick_phases([_flick(good), _flick(good)], _ctx())
    assert two.flicks_settled == 2 and two.phase_confidence == "hypothesis"
    three = compute_flick_phases([_flick(good)] * MIN_FLICKS_FOR_PHASE, _ctx())
    assert three.phase_confidence == "diagnosis"


# ---- медианы на смеси ----------------------------------------------------

def test_medians_over_usable_only():
    usable = _flick(_x([3, 1, 0.6, 0.3, 0.3, 0.3]))
    not_arrived = _flick(_x([3, 2, 1.5, 1.2]))
    rep = compute_flick_phases([usable, not_arrived, usable, usable], _ctx())
    assert rep.flicks_analysed == 4 and rep.flicks_settled == 3
    assert rep.settle_time_frames_median is not None


# ---- формат --------------------------------------------------------------

def test_format_mentions_settle_ms_and_confidence():
    rep = compute_flick_phases([_flick(_x([3, 1, 0.6, 0.3, 0.3, 0.3]))], _ctx())
    text = format_flick_phases(rep, _ctx())
    assert "ФАЗЫ ФЛИКА" in text
    assert "мс" in text
