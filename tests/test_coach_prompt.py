# -*- coding: utf-8 -*-
"""Тесты системного промпта и пользовательского текста коуча (Stage B1)."""
import json
from pathlib import Path

from coach.drill_catalog import menu_for_prompt
from coach.prompt import SYSTEM_PROMPT, build_user_text

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "friend_clip3.json"


def test_system_prompt_has_groundedness_rules():
    low = SYSTEM_PROMPT.lower()
    # числа — только из JSON, запрет выдумывать
    assert "json" in low
    assert "запрещено" in low or "запрещаю" in low
    # картинки — только контекст, не источник чисел
    assert "кадр" in low
    # confidence-язык: гипотеза != диагноз
    assert "гипотез" in low
    assert "диагноз" in low


def test_system_prompt_is_russian_coach_role():
    low = SYSTEM_PROMPT.lower()
    assert "коуч" in low or "тренер" in low
    assert "русск" in low


def test_system_prompt_forbids_raw_jargon_in_prose():
    # summary/explanation — для игрока, без сырых HU-чисел и статжаргона;
    # эти цифры показываются отдельно, уже с пояснением (см. labels.js)
    low = SYSTEM_PROMPT.lower()
    assert "summary" in low and "explanation" in low
    assert "жаргон" in low
    assert "mae" in low


def test_build_user_text_embeds_report_json():
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    text = build_user_text(report)
    assert '"player_id": "friend"' in text
    assert '"mae_hu": 1.349' in text


def test_build_user_text_mentions_frames_when_present():
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    text = build_user_text(report, frame_numbers=[177, 244])
    assert "177" in text
    assert "244" in text


def test_user_text_includes_catalog_menu():
    # без платформы — in-game меню (Фаза 4: kovaaks только при явном флаге)
    text = build_user_text({"findings": []}, frame_numbers=[])
    assert "consistency_ingame_t1_range_tempo" in text
    assert "consistency_t1_vt_ww5t_novice" not in text
    assert menu_for_prompt() in text
    # kovaaks в clip-блоке переключает меню
    kovaaks = build_user_text(
        {"findings": [], "clip": {"training_platform": "kovaaks"}},
        frame_numbers=[])
    assert "consistency_t1_vt_ww5t_novice" in kovaaks


def test_system_prompt_forbids_inventing_drills():
    assert "drill_id" in SYSTEM_PROMPT


def test_system_prompt_has_progress_rule():
    assert "drill_progress" in SYSTEM_PROMPT
    assert "progress_explained" in SYSTEM_PROMPT
    # запрет каузальности проговорён
    assert "сработал" in SYSTEM_PROMPT or "каузальн" in SYSTEM_PROMPT.lower()
