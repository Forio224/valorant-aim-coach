# -*- coding: utf-8 -*-
"""Профиль платформы: пороги движка перестают быть глобальными константами.

Клипы аим-тренажёра (Kovaak's/Aimbeast) — другой домен, чем Valorant: цель
не голова, а сфера, и калибровка порогов флика от Valorant не наследуется.
Профиль собирает эти пороги в одно место, оставляя поведение Valorant
байт-в-байт прежним.

Главный тест здесь — сверка профиля VALORANT с действующими модульными
константами: если кто-то поменяет константу и забудет профиль, тест упадёт.
"""
import pytest

from engine.platform_profile import (PlatformProfile, TRAINER, VALORANT,
                                     resolve_profile)


# ------------------------------------------------- профиль не разъехался с кодом

def test_valorant_profile_matches_live_constants():
    """Профиль Valorant == текущие константы движка, иначе калибровка врёт."""
    from engine.geometry import DEFAULT_DUEL_HU
    from engine.input_space import (VALORANT_HFOV_DEG,
                                    VALORANT_YAW_DEG_PER_COUNT)
    from engine.metrics import correction as corr
    from engine.metrics import flick_phase as fp

    assert VALORANT.duel_hu == DEFAULT_DUEL_HU
    assert VALORANT.deadband_hu == corr.DEADBAND_HU
    assert VALORANT.min_flick_speed_hu_s == corr.MIN_FLICK_SPEED_HU_S
    assert VALORANT.settle_s == corr.SETTLE_S
    assert VALORANT.stall_min_s == corr.STALL_MIN_S
    assert VALORANT.stall_speed_hu_s == corr.STALL_SPEED_HU_S
    assert VALORANT.undershoot_min_hu == corr.UNDERSHOOT_MIN_HU
    assert VALORANT.resume_drop_hu == corr.RESUME_DROP_HU
    assert VALORANT.near_band_hu == fp.NEAR_BAND_HU
    assert VALORANT.settle_tol_hu == fp.SETTLE_TOL_HU
    assert VALORANT.settle_stable_frames == fp.SETTLE_STABLE_FRAMES
    assert VALORANT.min_flicks_for_phase == fp.MIN_FLICKS_FOR_PHASE
    assert VALORANT.yaw_deg_per_count == VALORANT_YAW_DEG_PER_COUNT
    assert VALORANT.hfov_deg == VALORANT_HFOV_DEG


# ------------------------------------------------------------------ разрешение

@pytest.mark.parametrize("platform", [None, "ingame"])
def test_game_platforms_resolve_to_valorant(platform):
    """Игровой клип и отсутствие платформы — прежний профиль, прежние числа."""
    assert resolve_profile(platform) is VALORANT


@pytest.mark.parametrize("platform", ["kovaaks", "aimbeast"])
def test_trainer_platforms_resolve_to_trainer(platform):
    assert resolve_profile(platform) is TRAINER


def test_unknown_platform_falls_back_to_valorant():
    """Неизвестная платформа не роняет пайплайн: деградация в дефолт."""
    assert resolve_profile("quake-live") is VALORANT


# -------------------------------------------------------------------- инварианты

def test_trainer_starts_as_valorant_copy():
    """На первом этапе TRAINER = VALORANT по порогам: перекалибровка —
    отдельная задача, и она должна быть осознанной, а не случайной."""
    assert TRAINER.duel_hu == VALORANT.duel_hu
    assert TRAINER.near_band_hu == VALORANT.near_band_hu
    assert TRAINER.min_flick_speed_hu_s == VALORANT.min_flick_speed_hu_s
    assert TRAINER.name != VALORANT.name


def test_profile_is_frozen():
    """Пороги — не изменяемое глобальное состояние: правка только копией."""
    with pytest.raises(Exception):
        VALORANT.duel_hu = 99.0


def test_profiles_are_calibration_documented():
    """У профиля есть человекочитаемое имя — оно едет в отчёт и в промпт."""
    assert VALORANT.name == "valorant"
    assert TRAINER.name == "trainer"
