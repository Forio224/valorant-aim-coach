# -*- coding: utf-8 -*-
"""Парсер CSV-статистики KovaaK's.

Тренажёр пишет рядом с каждым прогоном файл вида
`<сценарий> - Challenge - <дата> Stats.csv` из трёх блоков, разделённых
пустыми строками: построчные килы, сводка по оружию и key:value-хвост с
настройками. Этот файл — готовый ground truth: моменты попаданий и TTK в нём
уже размечены самим тренажёром, без детектора и без ручной разметки.

Здесь же проверяется устойчивость к неполным файлам: прогон могли прервать,
и половина разбора всё равно полезнее отказа.
"""
import pytest

from engine.trainer_stats import ShotEvent
from engine.trainer_stats.kovaaks import parse_kovaaks_csv

FULL = """Kill #,Timestamp,Bot,Weapon,TTK,Damage Done,Damage Possible,Efficiency,Cheated
1,13:37:57.929,Bot 1,Gun,0.512s,100,100,1,0
2,13:37:58.741,Bot 2,Gun,0.633s,100,100,1,0
3,13:38:00.129,Bot 3,Gun,0.404s,100,100,1,0

Weapon,Shots,Hits,Damage Done,Damage Possible
Gun,12,3,300,1200

Scenario:,VT Pasu Rasp Intermediate S5
Score:,1284.56
Game Version:,3.1.3
Sens Scale:,Valorant
Horiz Sens:,0.35
Vert Sens:,0.35
FOV:,103
Resolution:,1920x1080
Avg FPS:,239.81
Avg TTK:,0.516
Pause Count:,0
"""


def _write(tmp_path, text, name="VT Pasu - Challenge - 2026.09.22 Stats.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------- события

def test_parses_every_kill_as_a_hit(tmp_path):
    session = parse_kovaaks_csv(_write(tmp_path, FULL))
    assert len(session.events) == 3
    assert all(isinstance(e, ShotEvent) for e in session.events)
    assert all(e.hit for e in session.events)


def test_timestamps_are_relative_to_session_start(tmp_path):
    """Видео и лог стартуют в разные моменты, поэтому абсолютное время суток
    бесполезно — движку нужны секунды от начала прогона."""
    session = parse_kovaaks_csv(_write(tmp_path, FULL))
    times = [e.t_seconds for e in session.events]
    assert times[0] == 0.0
    assert times[1] == pytest.approx(0.812, abs=1e-3)
    assert times[2] == pytest.approx(2.200, abs=1e-3)


def test_ttk_suffix_is_stripped(tmp_path):
    session = parse_kovaaks_csv(_write(tmp_path, FULL))
    assert session.events[0].ttk == pytest.approx(0.512)
    assert session.events[2].ttk == pytest.approx(0.404)


def test_target_id_carries_bot_label(tmp_path):
    session = parse_kovaaks_csv(_write(tmp_path, FULL))
    assert session.events[0].target_id == "Bot 1"


def test_events_are_sorted_by_time(tmp_path):
    session = parse_kovaaks_csv(_write(tmp_path, FULL))
    times = [e.t_seconds for e in session.events]
    assert times == sorted(times)


# -------------------------------------------------------------------- сводка

def test_reads_weapon_totals(tmp_path):
    session = parse_kovaaks_csv(_write(tmp_path, FULL))
    assert session.shots == 12
    assert session.hits == 3
    assert session.accuracy == pytest.approx(0.25)


def test_reads_settings_tail(tmp_path):
    session = parse_kovaaks_csv(_write(tmp_path, FULL))
    assert session.scenario == "VT Pasu Rasp Intermediate S5"
    assert session.score == pytest.approx(1284.56)
    assert session.avg_ttk == pytest.approx(0.516)
    assert session.fov == pytest.approx(103.0)
    assert session.horiz_sens == pytest.approx(0.35)
    assert session.sens_scale == "Valorant"
    assert session.resolution == "1920x1080"


def test_platform_is_tagged(tmp_path):
    assert parse_kovaaks_csv(_write(tmp_path, FULL)).platform == "kovaaks"


# --------------------------------------------------------------- устойчивость

def test_missing_kill_block_still_reads_summary(tmp_path):
    """Прогон без единого попадания — валидный прогон, а не сломанный файл."""
    text = FULL.split("Weapon,Shots", 1)[1]
    session = parse_kovaaks_csv(_write(tmp_path, "Weapon,Shots" + text))
    assert session.events == ()
    assert session.hits == 3


def test_missing_summary_still_reads_events(tmp_path):
    text = FULL.split("\n\n", 1)[0]
    session = parse_kovaaks_csv(_write(tmp_path, text))
    assert len(session.events) == 3
    assert session.shots is None
    assert session.accuracy is None


def test_midnight_rollover_does_not_go_negative(tmp_path):
    """Прогон через полночь: время суток убывает, но сессия не идёт назад."""
    text = FULL.replace("13:37:57.929", "23:59:59.500") \
               .replace("13:37:58.741", "00:00:00.300") \
               .replace("13:38:00.129", "00:00:01.700")
    session = parse_kovaaks_csv(_write(tmp_path, text))
    times = [e.t_seconds for e in session.events]
    assert times == sorted(times)
    assert times[1] == pytest.approx(0.8, abs=1e-3)
    assert times[2] == pytest.approx(2.2, abs=1e-3)


def test_garbage_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        parse_kovaaks_csv(_write(tmp_path, "это не csv статистики\n"))


def test_missing_file_raises(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        parse_kovaaks_csv(str(tmp_path / "нет.csv"))
