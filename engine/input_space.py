# -*- coding: utf-8 -*-
"""Input-space (Фаза 4): sens/eDPI перестают ехать в отчёт мёртвым грузом.

cm/360 — чистая мышиная арифметика (ни ширины кадра, ни FOV в формуле нет).
HU -> см — ЭКВИВАЛЕНТ, не измерение: перелёт — output-space прокси (стрейф
врага неотделим от руки), поле читается «столько руки объяснило бы перелёт
целиком». FOV-модель валидна только для 16:9 (стрельба с бедра).
"""
import math
from typing import Optional

from engine.clip_context import ClipContext

VALORANT_YAW_DEG_PER_COUNT = 0.07   # градусов на отсчёт мыши при sens 1.0
VALORANT_HFOV_DEG = 103.0           # горизонтальный FOV с бедра, 16:9

_ASPECT_16_9 = 16.0 / 9.0
_ASPECT_TOL = 0.01


def cm_per_360(edpi: Optional[float]) -> Optional[float]:
    """Сантиметров руки на полный оборот; None только при отсутствии eDPI."""
    if edpi is None or edpi <= 0:
        return None
    return 360.0 * 2.54 / (VALORANT_YAW_DEG_PER_COUNT * edpi)


def _is_16_9(ctx: ClipContext) -> bool:
    return abs(ctx.width / ctx.height - _ASPECT_16_9) <= _ASPECT_TOL


def cm_unavailable_reason(ctx: ClipContext) -> Optional[str]:
    """Почему см-эквивалент недоступен; None = доступен. Причины раздельны:
    cm/360 живёт и на stretched res, эквивалент перелёта — нет."""
    if ctx.edpi is None or ctx.edpi <= 0:
        return "нет eDPI"
    if not _is_16_9(ctx):
        return "аспект не 16:9"
    return None


def hu_to_cm_equiv(hu: float, head_height_px: float,
                   ctx: ClipContext) -> Optional[float]:
    """HU -> px -> градусы (тангенсная проекция) -> см руки через cm/360.

    При квадратных пикселях фокусное из HFOV общее для обеих осей."""
    if cm_unavailable_reason(ctx) is not None:
        return None
    px = abs(hu) * head_height_px
    half_w = ctx.width / 2.0
    focal_px = half_w / math.tan(math.radians(VALORANT_HFOV_DEG / 2.0))
    degrees = math.degrees(math.atan(px / focal_px))
    return degrees / 360.0 * cm_per_360(ctx.edpi)
