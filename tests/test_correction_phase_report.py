# -*- coding: utf-8 -*-
"""Встройка фаз-метрик в correction-finding (Фаза 2A) — синтетика, без dataset."""
from aim_metrics import FrameSample
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.metrics.flick_phase import compute_flick_phases
from engine.report import _correction_finding


def _ctx(fps: float = 60.0) -> ClipContext:
    return ClipContext(player_id="p", clip_id="c", fps=fps,
                       width=1920, height=1080, frame_count=10000)


def _flick(radials, start=100, track_id=1) -> Episode:
    samples = tuple(
        FrameSample(frame_idx=start + i, dx_hu=r, dy_hu=0.0,
                    radial_hu=r, head_height_px=63.0)
        for i, r in enumerate(radials))
    return Episode(track_id=track_id, start_frame=start,
                   end_frame=start + len(radials) - 1, samples=samples,
                   kind="flick", distance_bucket="mid", multi_enemy=False,
                   multi_from_frame=None, duel_frames=0,
                   peak_closing_speed_hu_s=50.0)


def test_correction_values_keep_old_keys_and_gain_phase_keys():
    eps = [_flick([3, 1, 0.6, 0.3, 0.3, 0.3], start=100, track_id=1)]
    finding = _correction_finding(eps, _ctx(), duel_hu=3.0)
    values = finding["values"]
    # старые ключи Фазы 1 на месте (от них зависит build_criterion)
    for key in ("flicks_total", "flicks_analysed", "x_overshoots",
                "x_undershoots", "y_overshoots", "y_undershoots"):
        assert key in values
    # новые фаз-ключи присутствуют и совпадают с compute_flick_phases
    ph = compute_flick_phases(eps, _ctx())
    assert values["settle_time_frames_median"] == ph.settle_time_frames_median
    assert values["flick_overshoot_hu_median"] == ph.flick_overshoot_hu_median
    assert values["correction_path_hu_median"] == ph.correction_path_hu_median
    assert values["phase_confidence"] == ph.phase_confidence
    assert values["flicks_settled"] == ph.flicks_settled
    # settle_time_ms выведен из кадров и fps
    assert values["settle_time_ms_median"] == round(
        1000 * ph.settle_time_frames_median / 60.0)


def test_phase_keys_null_when_no_usable_flicks():
    eps = [_flick([3, 2, 1.5, 1.2], start=100)]     # не дошёл
    values = _correction_finding(eps, _ctx(), duel_hu=3.0)["values"]
    assert values["settle_time_frames_median"] is None
    assert values["settle_time_ms_median"] is None
    assert values["phase_confidence"] == "insufficient"


def _flick_xy(offsets, start=100, track_id=1) -> Episode:
    """Флик из знаковых (dx, dy); radial = hypot — для перелёта через центр."""
    samples = tuple(
        FrameSample(frame_idx=start + i, dx_hu=dx, dy_hu=dy,
                    radial_hu=(dx * dx + dy * dy) ** 0.5, head_height_px=63.0)
        for i, (dx, dy) in enumerate(offsets))
    return Episode(track_id=track_id, start_frame=start,
                   end_frame=start + len(offsets) - 1, samples=samples,
                   kind="flick", distance_bucket="mid", multi_enemy=False,
                   multi_from_frame=None, duel_frames=0,
                   peak_closing_speed_hu_s=50.0)


def test_overshoot_frame_surfaced_in_evidence():
    # dx пересекает центр: +...+ затем -0.6 (пик) → истинный перелёт 0.6 на кадре103
    offs = [(3, 0), (1.5, 0), (0.5, 0), (-0.6, 0), (-0.4, 0),
            (-0.2, 0), (-0.1, 0), (-0.1, 0)]
    eps = [_flick_xy(offs, start=100)]
    finding = _correction_finding(eps, _ctx(), duel_hu=3.0)
    ph = compute_flick_phases(eps, _ctx())
    frame = ph.phases[0].overshoot_evidence_frame
    assert frame == 103
    # фаз-улика присутствует, с отличимым маркером «пик доводки»
    ev = [e for e in finding["evidence"]
          if e["frame"] == frame and "пик доводки" in e["note"]]
    assert len(ev) == 1
    assert ev[0]["episode"] == 1
    assert ev[0]["dx_hu"] == -0.6          # геометрия реального кадра проброшена
    assert str(ph.phases[0].flick_overshoot_hu) in ev[0]["note"]


def test_no_phase_overshoot_evidence_when_no_crossing():
    # монотонный подход без смены знака → фаз-улики перелёта нет
    eps = [_flick([3, 1, 0.6, 0.3, 0.3, 0.3], start=100)]
    finding = _correction_finding(eps, _ctx(), duel_hu=3.0)
    assert all("пик доводки" not in e["note"] for e in finding["evidence"])
