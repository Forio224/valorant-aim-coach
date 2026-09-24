# -*- coding: utf-8 -*-
"""Парсер статистики Aimbeast.

В отличие от KovaaK's, формат экспорта Aimbeast недокументирован и здесь не
подтверждён на настоящем файле. Поэтому парсер намеренно толерантный: он
ищет колонки по именам, а не по позициям, понимает и CSV, и JSON, и
принимает время как в секундах, так и временем суток.

Когда появится реальный экспорт, сверка с ним — один прогон этих тестов на
настоящем файле; менять придётся списки синонимов колонок, а не логику.
"""
import json

import pytest

from engine.trainer_stats import parse_stats
from engine.trainer_stats.aimbeast import parse_aimbeast_stats

CSV_SECONDS = """Time,Hit,TTK,Target
0.000,1,0.512,Bot 1
0.812,0,,Bot 2
2.200,1,0.404,Bot 3
"""

CSV_CLOCK = """Timestamp,Result,Time To Kill,Target Id
13:37:57.929,hit,0.512s,t1
13:37:58.741,miss,,t2
13:38:00.129,hit,0.404s,t3
"""

JSON_EXPORT = json.dumps({
    "scenario": "Tile Frenzy",
    "score": 1284.5,
    "shots": 12,
    "hits": 3,
    "events": [
        {"time": 0.0, "hit": True, "ttk": 0.512, "target": "Bot 1"},
        {"time": 0.812, "hit": False},
        {"time": 2.2, "hit": True, "ttk": 0.404},
    ],
})


def _write(tmp_path, text, name):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------ CSV, секунды

def test_reads_csv_with_seconds(tmp_path):
    session = parse_aimbeast_stats(_write(tmp_path, CSV_SECONDS, "a.csv"))
    assert session.platform == "aimbeast"
    assert len(session.events) == 3
    assert [e.t_seconds for e in session.events] == pytest.approx(
        [0.0, 0.812, 2.2])


def test_hit_flag_from_numbers(tmp_path):
    session = parse_aimbeast_stats(_write(tmp_path, CSV_SECONDS, "a.csv"))
    assert [e.hit for e in session.events] == [True, False, True]


def test_derives_totals_from_events_when_summary_absent(tmp_path):
    """Без сводки accuracy всё равно считается — по самим событиям."""
    session = parse_aimbeast_stats(_write(tmp_path, CSV_SECONDS, "a.csv"))
    assert session.shots == 3
    assert session.hits == 2
    assert session.accuracy == pytest.approx(2 / 3)


# -------------------------------------------------------------- CSV, время суток

def test_reads_csv_with_clock_and_word_results(tmp_path):
    session = parse_aimbeast_stats(_write(tmp_path, CSV_CLOCK, "b.csv"))
    assert [e.hit for e in session.events] == [True, False, True]
    assert [e.t_seconds for e in session.events] == pytest.approx(
        [0.0, 0.812, 2.2], abs=1e-3)


def test_ttk_suffix_stripped_and_blank_is_none(tmp_path):
    session = parse_aimbeast_stats(_write(tmp_path, CSV_CLOCK, "b.csv"))
    assert session.events[0].ttk == pytest.approx(0.512)
    assert session.events[1].ttk is None


def test_target_column_synonyms(tmp_path):
    session = parse_aimbeast_stats(_write(tmp_path, CSV_CLOCK, "b.csv"))
    assert session.events[0].target_id == "t1"


# ----------------------------------------------------------------------- JSON

def test_reads_json_export(tmp_path):
    session = parse_aimbeast_stats(_write(tmp_path, JSON_EXPORT, "c.json"))
    assert session.scenario == "Tile Frenzy"
    assert session.score == pytest.approx(1284.5)
    assert session.shots == 12          # сводка приоритетнее счёта событий
    assert session.hits == 3
    assert len(session.events) == 3
    assert session.events[2].ttk == pytest.approx(0.404)


# ------------------------------------------------------------------ диспетчер

def test_parse_stats_routes_by_platform(tmp_path):
    session = parse_stats(_write(tmp_path, CSV_SECONDS, "a.csv"), "aimbeast")
    assert session.platform == "aimbeast"


def test_parse_stats_rejects_unknown_platform(tmp_path):
    with pytest.raises(ValueError):
        parse_stats(_write(tmp_path, CSV_SECONDS, "a.csv"), "quake")


# --------------------------------------------------------------- устойчивость

def test_unrecognisable_columns_raise_with_actionable_message(tmp_path):
    """Сообщение должно называть, чего не хватило: формат не подтверждён,
    и игрок с непривычным экспортом должен понять, что прислать."""
    path = _write(tmp_path, "alpha,beta\n1,2\n", "d.csv")
    with pytest.raises(ValueError) as err:
        parse_aimbeast_stats(path)
    assert "врем" in str(err.value).lower()


def test_missing_file_raises(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        parse_aimbeast_stats(str(tmp_path / "нет.csv"))


# ------------------------------------------- настоящий файл Aimbeast (2026)
# Aimbeast пишет Statistics/<режим>/<сценарий>.json: UTF-16 с BOM, история
# ВСЕХ прогонов параллельными массивами, моментов выстрелов нет вовсе
# (источник: разбор файлов в Bassel-Bakr/KovOBS). Разбирать его пока не
# умеем, но игрок должен получить объяснение, а не UnicodeDecodeError.

def _write_utf16(tmp_path, payload):
    path = tmp_path / "1 WALL 6 TARGETS.json"
    path.write_bytes(json.dumps(payload).encode("utf-16"))
    return str(path)


def test_real_scenario_history_file_gets_explained(tmp_path):
    path = _write_utf16(tmp_path, {"Date": ["19/9/2026"], "Score": [812.0],
                                   "Accuracy": [0.81], "TTK": [0.41]})
    with pytest.raises(ValueError) as err:
        parse_aimbeast_stats(path)
    message = str(err.value).lower()
    assert "codec" not in message
    assert "моментов выстрелов" in message


def test_utf16_event_log_is_still_readable(tmp_path):
    """Кодировка — не повод отказывать: построчный лог в UTF-16 читаем."""
    path = _write_utf16(tmp_path, [{"time": 0.5, "hit": 1},
                                   {"time": 1.2, "hit": 0}])
    session = parse_aimbeast_stats(path)
    assert len(session.events) == 2
