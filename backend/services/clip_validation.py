# -*- coding: utf-8 -*-
"""Валидация клипа до пайплайна (Этап 2 запуска).

Мусорный файл не должен доехать до GPU, а длина клипа ограничена кэпом
из юнит-экономики (docs/UNIT_ECONOMICS.md): цена разбора растёт линейно
от длительности, и 300-мегабайтный лимит её не ограничивает.

cv2 вместо ffprobe: OpenCV уже в стеке, отдельный бинарник не нужен.
"""
import os
from dataclasses import dataclass

DEFAULT_MAX_CLIP_SECONDS = 120.0


class ClipValidationError(ValueError):
    """Человеческое сообщение — уходит игроку как есть."""


@dataclass(frozen=True)
class ClipInfo:
    duration_s: float
    fps: float
    width: int
    height: int


def max_clip_seconds() -> float:
    return float(os.getenv("MAX_CLIP_SECONDS", str(DEFAULT_MAX_CLIP_SECONDS)))


def validate_clip(path: str, *, max_seconds: float = None) -> ClipInfo:
    """Проверить, что это читаемое видео разумной длины."""
    import cv2

    limit = max_clip_seconds() if max_seconds is None else float(max_seconds)
    cap = cv2.VideoCapture(path)
    try:
        ok_first = cap.isOpened() and cap.read()[0]
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()

    if not ok_first or fps <= 0 or frames <= 0:
        raise ClipValidationError(
            "Файл не удалось прочитать как видео. Поддерживаются обычные "
            "записи геймплея (mp4/avi/mov/mkv) без повреждений.")
    duration_s = frames / fps
    if duration_s > limit:
        raise ClipValidationError(
            f"Клип длиннее лимита: {duration_s:.0f} сек при потолке "
            f"{limit:.0f} сек. Обрежьте запись до нужного боя — движку "
            f"хватает пары раундов.")
    return ClipInfo(duration_s=duration_s, fps=fps, width=width,
                    height=height)
