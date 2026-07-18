"""Smoke-тест переезда ядра геометрии в engine.geometry.

Задача Task 1 фазы 3 — механический перенос: ни одно число не меняется, а
`aim_metrics` реэкспортирует те же объекты (существующие импорты не ломаются).
Регрессия остального поведения покрыта полным сьютом; здесь проверяем сам шов.
"""

import numpy as np

import aim_metrics
from engine import geometry
from engine.geometry import (
    DEFAULT_DUEL_HU,
    MIN_HEAD_PX,
    AimPassport,
    FrameSample,
    Head,
    compute_passport,
    pick_target,
    sample_frame,
)


def test_core_names_importable_from_new_home():
    """Каждое имя ядра доступно из engine.geometry."""
    assert isinstance(DEFAULT_DUEL_HU, float)
    assert isinstance(MIN_HEAD_PX, float)
    for obj in (Head, FrameSample, AimPassport, pick_target, sample_frame,
                compute_passport):
        assert obj is not None


def test_aim_metrics_reexports_same_objects():
    """aim_metrics.<name> — ТОТ ЖЕ объект, что engine.geometry.<name> (реэкспорт)."""
    assert aim_metrics.Head is geometry.Head
    assert aim_metrics.FrameSample is geometry.FrameSample
    assert aim_metrics.AimPassport is geometry.AimPassport
    assert aim_metrics.pick_target is geometry.pick_target
    assert aim_metrics.sample_frame is geometry.sample_frame
    assert aim_metrics.compute_passport is geometry.compute_passport
    assert aim_metrics.DEFAULT_DUEL_HU == geometry.DEFAULT_DUEL_HU
    assert aim_metrics.MIN_HEAD_PX == geometry.MIN_HEAD_PX


def test_pick_target_picks_nearest_head():
    """pick_target выбирает голову, ближайшую к прицелу."""
    crosshair = (100.0, 100.0)
    near = Head(cx=105.0, cy=100.0, height_px=30.0)
    far = Head(cx=300.0, cy=100.0, height_px=30.0)
    assert pick_target([far, near], crosshair) is near
    assert pick_target([], crosshair) is None


def test_sample_frame_normalises_into_head_units():
    """sample_frame переводит смещение в Head Units через высоту головы."""
    crosshair = (100.0, 100.0)
    head = Head(cx=130.0, cy=70.0, height_px=30.0)  # +1 HU вправо, -1 HU вверх
    s = sample_frame(7, head, crosshair)
    assert s.frame_idx == 7
    assert s.dx_hu == 1.0
    assert s.dy_hu == -1.0
    assert s.radial_hu == float(np.hypot(1.0, -1.0))
    assert s.head_height_px == 30.0


def test_min_head_px_guards_zero_height():
    """Нулевая высота головы не роняет нормировку (защита MIN_HEAD_PX)."""
    s = sample_frame(0, Head(cx=101.0, cy=100.0, height_px=0.0), (100.0, 100.0))
    assert s.dx_hu == 1.0 / MIN_HEAD_PX


def test_compute_passport_on_synthetic_samples():
    """compute_passport агрегирует синтетические сэмплы предсказуемо."""
    samples = [
        FrameSample(0, 0.0, 0.0, 0.0, 30.0),
        FrameSample(1, 2.0, 0.0, 2.0, 30.0),
    ]
    p = compute_passport(samples, duel_hu=DEFAULT_DUEL_HU)
    assert p.frames_measured == 2
    assert p.duel_frames == 2  # оба radial <= 3.0
    assert p.overall_mae_hu == 1.0
    empty = compute_passport([], duel_hu=DEFAULT_DUEL_HU)
    assert empty.frames_measured == 0
