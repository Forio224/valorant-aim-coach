# -*- coding: utf-8 -*-
"""Источник целей для клипов аим-тренажёра (KovaaK's / Aimbeast).

Зачем не YOLO. Веса `heads_v3` обучены на одном классе `head` — головах
врагов Valorant. Цель тренажёра это однотонная сфера контрастного цвета на
нейтральном фоне: домен другой, и переучивать детектор ради задачи, которую
решает цветовая сегментация, было бы лишней работой и лишними 100 GPU-с на
минуту видео.

Зачем не `CentroidHeadDetector`. Тот детектор заточен под Valorant: HUD-зоны,
силуэт тела, «верхние 22% bbox = голова», исключение модели игрока. На сферах
всё это мешает. Переиспользуется только `HSVRange` — в нём уже решена
обёртка красного тона через 0°.

Контракт наружу — ровно тот, что ждёт `run_pipeline(detector=...)`:
вызываемое от пути к видео, возвращающее `{frame_idx: [Head, ...]}`.
`height_px` цели — диаметр сферы: он играет ту же роль, что высота головы,
поэтому HU-нормировка и весь движок метрик работают без изменений.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from backend.centroid_head_detector import HSVRange
from engine.episodes import HeadsByFrame
from engine.geometry import Head

# Типичные цвета целей. Тренажёры позволяют красить цели произвольно,
# поэтому это отправная точка, а не исчерпывающий список.
PRESETS = {
    "orange": HSVRange(h_min=5, h_max=25, s_min=120, s_max=255,
                       v_min=100, v_max=255),
    "red":    HSVRange(h_min=0, h_max=10, s_min=120, s_max=255,
                       v_min=90, v_max=255, h_min2=170, h_max2=179),
    "green":  HSVRange(h_min=40, h_max=80, s_min=90, s_max=255,
                       v_min=80, v_max=255),
    "purple": HSVRange(h_min=125, h_max=160, s_min=90, s_max=255,
                       v_min=80, v_max=255),
    "blue":   HSVRange(h_min=95, h_max=125, s_min=110, s_max=255,
                       v_min=80, v_max=255),
}

DEFAULT_PRESET = "orange"


@dataclass(frozen=True)
class TargetParams:
    """Ручки сегментации. Дефолты нарочно мягкие: цвет цели у каждого свой,
    а слишком строгий фильтр молча отдаёт пустой клип вместо разбора."""
    hsv: HSVRange
    min_area_px: int = 30          # мельче — шум компрессии, не цель
    max_radius_frac: float = 1.0   # 1.0 = без ограничения; доля высоты кадра
    min_circularity: float = 0.6   # площадь / площадь описанной окружности
    morph_kernel_px: int = 3       # закрывает дыры от сетки прицела на цели

    @classmethod
    def from_preset(cls, name: Optional[str] = None, **kw) -> "TargetParams":
        preset = PRESETS.get(name or DEFAULT_PRESET)
        if preset is None:
            raise ValueError(
                f"неизвестный пресет цвета цели: {name!r}; "
                f"доступны: {', '.join(sorted(PRESETS))}")
        return cls(hsv=preset, **kw)


def _mask(frame, hsv_range: HSVRange, kernel_px: int):
    """Бинарная маска пикселей цвета цели, с обёрткой красного через 0°."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([hsv_range.h_min, hsv_range.s_min, hsv_range.v_min], np.uint8),
        np.array([hsv_range.h_max, hsv_range.s_max, hsv_range.v_max], np.uint8))

    if hsv_range.h_min2 is not None and hsv_range.h_max2 is not None:
        mask = cv2.bitwise_or(mask, cv2.inRange(
            hsv,
            np.array([hsv_range.h_min2, hsv_range.s_min, hsv_range.v_min],
                     np.uint8),
            np.array([hsv_range.h_max2, hsv_range.s_max, hsv_range.v_max],
                     np.uint8)))

    if kernel_px > 0:
        kernel = np.ones((kernel_px, kernel_px), np.uint8)
        # OPEN убирает одиночные пиксели, CLOSE — дыру от прицела на цели.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def detect_targets_in_frame(frame, params: TargetParams) -> List[Head]:
    """Цели на одном кадре. Чистая функция от numpy-кадра — её и тестируем."""
    import cv2
    import math

    mask = _mask(frame, params.hsv, params.morph_kernel_px)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    frame_height = frame.shape[0]
    max_radius = params.max_radius_frac * frame_height

    heads: List[Head] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < params.min_area_px:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        if radius <= 0 or radius > max_radius:
            continue
        # Компактность: у сферы ~1.0, у полосы HUD того же цвета — близко к 0.
        if area / (math.pi * radius * radius) < params.min_circularity:
            continue
        heads.append(Head(cx=float(cx), cy=float(cy),
                          height_px=float(2.0 * radius)))
    return heads


def detect_targets(video_path: str, params: TargetParams) -> HeadsByFrame:
    """Все цели на каждом кадре клипа.

    Как и у YOLO-источника, кадры без целей в словарь не попадают —
    `segment_episodes` трактует пропуск как разрыв трека.
    """
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"не удалось открыть видео: {video_path}")

    heads_by_frame: Dict[int, Sequence[Head]] = {}
    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            heads = detect_targets_in_frame(frame, params)
            if heads:
                heads_by_frame[frame_idx] = heads
            frame_idx += 1
    finally:
        cap.release()
    return heads_by_frame


SOURCE_NAME = "trainer_colour"


def make_trainer_detector(params: TargetParams):
    """Detector для `run_pipeline`: замыкает параметры, оставляя путь к видео.

    Атрибут `source` называет источник целей — он едет в логи и позволяет
    убедиться, какой детектор выбран, не запуская его.
    """
    def detector(video_path: str) -> HeadsByFrame:
        return detect_targets(video_path, params)
    detector.source = SOURCE_NAME
    return detector
