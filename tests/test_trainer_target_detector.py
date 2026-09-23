# -*- coding: utf-8 -*-
"""Детектор целей аим-тренажёра: сферы вместо голов.

Домен проще валорантового: однотонный шар контрастного цвета на нейтральном
фоне, без HUD-силуэтов и модели игрока. Поэтому YOLO здесь не нужен —
хватает цветовой сегментации, а `height_px` цели берётся как диаметр круга
(играет ту же роль, что высота головы, и HU-нормировка работает как была).

Тесты уровня кадра — на numpy-массивах: никаких кодеков, никакого датасета.
Видео-обёртка проверяется одним отдельным тестом.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from backend.trainer_target_detector import (PRESETS, TargetParams,
                                             detect_targets,
                                             detect_targets_in_frame,
                                             make_trainer_detector)

W, H = 640, 360
BG = (60, 60, 60)          # нейтральный серый фон, как в тренажёрах
TARGET_BGR = (0, 90, 255)  # оранжевый шар


def _frame(circles=(), bg=BG):
    """Кадр с закрашенными кругами: (cx, cy, r) в пикселях."""
    img = np.full((H, W, 3), bg, dtype=np.uint8)
    for cx, cy, r in circles:
        cv2.circle(img, (int(cx), int(cy)), int(r), TARGET_BGR, -1)
    return img


def _params(**kw):
    return TargetParams(hsv=PRESETS["orange"], **kw)


# ------------------------------------------------------------ базовая детекция

def test_finds_single_target_with_correct_centre_and_size():
    heads = detect_targets_in_frame(_frame([(200, 150, 20)]), _params())
    assert len(heads) == 1
    head = heads[0]
    assert head.cx == pytest.approx(200, abs=2)
    assert head.cy == pytest.approx(150, abs=2)
    # height_px — диаметр: именно он заменяет высоту головы в HU-нормировке
    assert head.height_px == pytest.approx(40, abs=4)


def test_empty_frame_yields_no_targets():
    assert detect_targets_in_frame(_frame(), _params()) == []


def test_finds_several_targets():
    heads = detect_targets_in_frame(
        _frame([(120, 100, 18), (400, 240, 22)]), _params())
    assert len(heads) == 2
    xs = sorted(h.cx for h in heads)
    assert xs[0] == pytest.approx(120, abs=2)
    assert xs[1] == pytest.approx(400, abs=2)


def test_wrong_colour_is_not_a_target():
    """Фон и посторонние объекты другого тона не должны считаться целью."""
    img = _frame()
    cv2.circle(img, (300, 180), 25, (255, 120, 0), -1)   # синий, не оранжевый
    assert detect_targets_in_frame(img, _params()) == []


# ----------------------------------------------------------------- фильтрация

def test_speck_below_min_area_is_rejected():
    """Одиночные пиксели цвета цели — шум компрессии, не цель."""
    heads = detect_targets_in_frame(_frame([(200, 150, 1)]),
                                    _params(min_area_px=50))
    assert heads == []


def test_oversized_blob_is_rejected():
    """Заливка полкадра — это фон/вспышка, а не цель."""
    heads = detect_targets_in_frame(_frame([(320, 180, 200)]),
                                    _params(max_radius_frac=0.2))
    assert heads == []


def test_non_circular_blob_is_rejected():
    """Полоса UI того же цвета не круглая — отсекается по компактности."""
    img = _frame()
    cv2.rectangle(img, (50, 20), (600, 40), TARGET_BGR, -1)
    assert detect_targets_in_frame(img, _params(min_circularity=0.7)) == []


def test_circularity_gate_can_be_disabled():
    """Порог настраиваемый: не все тренажёры рисуют идеальные сферы."""
    img = _frame()
    cv2.rectangle(img, (50, 20), (600, 60), TARGET_BGR, -1)
    assert detect_targets_in_frame(img, _params(min_circularity=0.0))


# ------------------------------------------------------------------- пресеты

def test_presets_cover_common_target_colours():
    for name in ("orange", "red", "green", "purple"):
        assert name in PRESETS


def test_red_preset_handles_hue_wraparound():
    """Красный лежит по обе стороны 0° в HSV — нужен второй диапазон."""
    assert PRESETS["red"].h_min2 is not None


# ------------------------------------------------------- видео-обёртка и фабрика

def test_detect_targets_over_video(tmp_path):
    """Обёртка возвращает HeadsByFrame: кадры без целей в словарь не попадают."""
    path = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (W, H))
    if not writer.isOpened():
        pytest.skip("нет кодека mp4v в этой сборке OpenCV")
    for i in range(6):
        writer.write(_frame([(100 + i * 40, 180, 20)]) if i < 4 else _frame())
    writer.release()

    heads_by_frame = detect_targets(path, _params())
    assert set(heads_by_frame) <= {0, 1, 2, 3}
    assert heads_by_frame, "цели должны найтись хотя бы на части кадров"
    assert all(len(v) == 1 for v in heads_by_frame.values())


def test_make_trainer_detector_matches_pipeline_contract(tmp_path):
    """Фабрика отдаёт ровно то, что run_pipeline ждёт в параметре detector:
    вызываемое от одного пути к видео."""
    path = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (W, H))
    if not writer.isOpened():
        pytest.skip("нет кодека mp4v в этой сборке OpenCV")
    writer.write(_frame([(320, 180, 20)]))
    writer.release()

    detector = make_trainer_detector(_params())
    assert callable(detector)
    assert isinstance(detector(path), dict)


def test_missing_video_fails_loudly(tmp_path):
    with pytest.raises(ValueError):
        detect_targets(str(tmp_path / "нет-такого.mp4"), _params())
