# -*- coding: utf-8 -*-
"""Профиль платформы: пороги движка, зависящие от источника клипа.

Движок калиброван на клипах Valorant: голова врага как единица длины (HU),
пороги флика и settle подобраны под дуэли в матче. Клип из аим-тренажёра —
другой домен: цель это сфера, дистанции и скорости свои, и наследовать
Valorant-калибровку было бы молчаливой ошибкой.

Профиль собирает эти пороги в одно frozen-место. Модульные константы в
`geometry`/`correction`/`flick_phase`/`input_space` остаются дефолтами —
поведение Valorant не меняется, а вызывающий код может передать другой
профиль.

TRAINER на этом этапе — копия VALORANT по числам. Это сознательно:
перекалибровка требует записанных сессий тренажёра с логами и должна быть
отдельной, измеренной работой, а не догадкой при заведении модуля.
"""
from dataclasses import dataclass, replace
from typing import Optional

from engine.geometry import DEFAULT_DUEL_HU
from engine.input_space import (VALORANT_HFOV_DEG,
                                VALORANT_YAW_DEG_PER_COUNT)
from engine.metrics.correction import (DEADBAND_HU, MIN_FLICK_SPEED_HU_S,
                                       RESUME_DROP_HU, SETTLE_S,
                                       STALL_MIN_S, STALL_SPEED_HU_S,
                                       UNDERSHOOT_MIN_HU)
from engine.metrics.flick_phase import (MIN_FLICKS_FOR_PHASE, NEAR_BAND_HU,
                                        SETTLE_STABLE_FRAMES, SETTLE_TOL_HU)


@dataclass(frozen=True)
class PlatformProfile:
    """Всё, что калибруется под источник клипа, одним объектом.

    `name` едет в отчёт и в промпт коуча: разбор, посчитанный по порогам
    тренажёра, не должен выдавать себя за игровой.
    """
    name: str

    # дуэль / геометрия
    duel_hu: float

    # коррекция: перелёт-недолёт
    deadband_hu: float
    min_flick_speed_hu_s: float
    settle_s: float
    stall_min_s: float
    stall_speed_hu_s: float
    undershoot_min_hu: float
    resume_drop_hu: float

    # фазы флика: баллистика -> settle
    near_band_hu: float
    settle_tol_hu: float
    settle_stable_frames: int
    min_flicks_for_phase: int

    # input-space: перевод сенсы в см/360 и HU в градусы
    yaw_deg_per_count: float
    hfov_deg: float


VALORANT = PlatformProfile(
    name="valorant",
    duel_hu=DEFAULT_DUEL_HU,
    deadband_hu=DEADBAND_HU,
    min_flick_speed_hu_s=MIN_FLICK_SPEED_HU_S,
    settle_s=SETTLE_S,
    stall_min_s=STALL_MIN_S,
    stall_speed_hu_s=STALL_SPEED_HU_S,
    undershoot_min_hu=UNDERSHOOT_MIN_HU,
    resume_drop_hu=RESUME_DROP_HU,
    near_band_hu=NEAR_BAND_HU,
    settle_tol_hu=SETTLE_TOL_HU,
    settle_stable_frames=SETTLE_STABLE_FRAMES,
    min_flicks_for_phase=MIN_FLICKS_FOR_PHASE,
    yaw_deg_per_count=VALORANT_YAW_DEG_PER_COUNT,
    hfov_deg=VALORANT_HFOV_DEG,
)

# Числа пока валорантовские — см. модульный docstring про перекалибровку.
# Игроки обычно калибруют тренажёр под ту же сенсу и FOV, что и в игре,
# поэтому input-space наследуется осознанно, а не по недосмотру.
TRAINER = replace(VALORANT, name="trainer")

_BY_PLATFORM = {
    "kovaaks": TRAINER,
    "aimbeast": TRAINER,
    "ingame": VALORANT,
}


def resolve_profile(training_platform: Optional[str]) -> PlatformProfile:
    """Профиль по значению `ClipContext.training_platform`.

    Неизвестная платформа деградирует в VALORANT, а не падает: источник
    клипа — пользовательский ввод, и разбор по дефолтным порогам полезнее
    отказа. Валидация допустимых значений живёт в `ClipContext`.
    """
    if training_platform is None:
        return VALORANT
    return _BY_PLATFORM.get(training_platform, VALORANT)
