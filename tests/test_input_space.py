# -*- coding: utf-8 -*-
"""Input-space: cm/360 из eDPI, HU->см-эквивалент, честные отказы (Фаза 4)."""
import pytest

from engine.clip_context import ClipContext
from engine.input_space import cm_per_360, cm_unavailable_reason, hu_to_cm_equiv


def _ctx(width=1920, height=1080, edpi=280.0):
    return ClipContext(player_id="p", clip_id="c", fps=60.0, width=width,
                       height=height, frame_count=1000, edpi=edpi)


def test_cm_per_360_matches_community_calculators():
    # 360 * 2.54 / (0.07 * 280) = 46.65 (сверено с калькуляторами)
    assert cm_per_360(280.0) == pytest.approx(46.65, abs=0.01)


def test_cm_per_360_none_without_edpi():
    assert cm_per_360(None) is None


def test_cm_per_360_survives_stretched_res():
    # мышиная арифметика: ни ширины кадра, ни FOV в формуле нет
    assert cm_unavailable_reason(_ctx(width=1280, height=960)) == "аспект не 16:9"
    assert cm_per_360(_ctx(width=1280, height=960).edpi) is not None


def test_reason_no_edpi_beats_aspect():
    assert cm_unavailable_reason(_ctx(edpi=None)) == "нет eDPI"
    assert cm_unavailable_reason(_ctx()) is None


def test_hu_to_cm_equiv_monotone_and_positive():
    cm1 = hu_to_cm_equiv(1.0, 63.0, _ctx())
    cm2 = hu_to_cm_equiv(2.0, 63.0, _ctx())
    assert cm1 is not None and cm1 > 0
    assert cm2 > cm1


def test_hu_to_cm_equiv_none_when_invalid():
    assert hu_to_cm_equiv(1.0, 63.0, _ctx(edpi=None)) is None
    assert hu_to_cm_equiv(1.0, 63.0, _ctx(width=1280, height=960)) is None
