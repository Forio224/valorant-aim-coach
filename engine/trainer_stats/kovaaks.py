# -*- coding: utf-8 -*-
"""Разбор CSV-статистики KovaaK's.

Файл `<сценарий> - Challenge - <дата> Stats.csv` состоит из блоков,
разделённых пустыми строками:

    Kill #,Timestamp,Bot,Weapon,TTK,...      построчные килы
    Weapon,Shots,Hits,...                    сводка по оружию
    Scenario:,...                            key:value хвост с настройками

Формат недокументирован и менялся между версиями тренажёра, поэтому парсер
читает блоки по их заголовкам, а не по порядковому номеру, и каждое поле
сводки необязательно: прерванный прогон должен разбираться частично.

Промахи построчно тренажёр не пишет — они видны только в сводке
Shots/Hits. Поэтому `events` содержит попадания, а accuracy берётся из
сводки.
"""
import csv
import os
from typing import Dict, List, Optional

from engine.trainer_stats import ShotEvent, TrainerSession

_SECONDS_PER_DAY = 24 * 60 * 60

# Ключи хвоста → поля TrainerSession. Двоеточие в ключе KovaaK's пишет сам.
_TEXT_FIELDS = {
    "scenario": "scenario",
    "sens scale": "sens_scale",
    "resolution": "resolution",
}
_FLOAT_FIELDS = {
    "score": "score",
    "avg ttk": "avg_ttk",
    "fov": "fov",
    "horiz sens": "horiz_sens",
}


def _parse_clock(value: str) -> Optional[float]:
    """`13:37:57.929` → секунды от полуночи."""
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (float(p) for p in parts)
    except ValueError:
        return None
    return hours * 3600.0 + minutes * 60.0 + seconds


def _parse_number(value: str) -> Optional[float]:
    """Число из ячейки; `0.512s` и `1 284,56` тоже считаются числом."""
    text = value.strip().rstrip("s").replace(",", ".").replace(" ", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_blocks(path: str) -> List[List[List[str]]]:
    """Строки файла → блоки, разделённые пустыми строками."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"нет файла статистики: {path}")

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    blocks: List[List[List[str]]] = []
    current: List[List[str]] = []
    for row in rows:
        if not any(cell.strip() for cell in row):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(row)
    if current:
        blocks.append(current)
    return blocks


def _header_of(block: List[List[str]]) -> str:
    return block[0][0].strip().lower() if block and block[0] else ""


def _relative_times(clocks: List[float]) -> List[float]:
    """Время суток → секунды от первого события, с учётом перехода за полночь.

    Прогон короче суток, поэтому убывание метки означает ровно одно: сутки
    сменились. Без этой поправки полуночная сессия давала бы отрицательные
    времена и ломала сортировку событий.
    """
    if not clocks:
        return []
    relative: List[float] = []
    previous = clocks[0]
    elapsed = 0.0
    for clock in clocks:
        step = clock - previous
        if step < 0:
            step += _SECONDS_PER_DAY
        elapsed += step
        relative.append(elapsed)
        previous = clock
    return relative


def _parse_kill_block(block: List[List[str]]) -> List[ShotEvent]:
    header = [cell.strip().lower() for cell in block[0]]
    index = {name: pos for pos, name in enumerate(header)}

    def cell(row: List[str], name: str) -> str:
        pos = index.get(name)
        return row[pos] if pos is not None and pos < len(row) else ""

    rows = [row for row in block[1:] if any(c.strip() for c in row)]
    clocks = [_parse_clock(cell(row, "timestamp")) for row in rows]

    # Строки без разбираемой метки времени не на что положить на ось.
    usable = [(row, clock) for row, clock in zip(rows, clocks)
              if clock is not None]
    if not usable:
        return []

    times = _relative_times([clock for _, clock in usable])
    return [
        ShotEvent(t_seconds=t, hit=True,
                  ttk=_parse_number(cell(row, "ttk")),
                  target_id=(cell(row, "bot").strip() or None))
        for (row, _), t in zip(usable, times)
    ]


def _parse_weapon_block(block: List[List[str]]) -> Dict[str, int]:
    """Сводка по оружию; при нескольких строках — суммы по всем."""
    header = [cell.strip().lower() for cell in block[0]]
    index = {name: pos for pos, name in enumerate(header)}
    totals: Dict[str, int] = {}
    for name in ("shots", "hits"):
        pos = index.get(name)
        if pos is None:
            continue
        values = [_parse_number(row[pos]) for row in block[1:]
                  if pos < len(row)]
        numbers = [v for v in values if v is not None]
        if numbers:
            totals[name] = int(sum(numbers))
    return totals


def _parse_tail_block(block: List[List[str]]) -> Dict[str, object]:
    fields: Dict[str, object] = {}
    for row in block:
        if len(row) < 2:
            continue
        key = row[0].strip().rstrip(":").lower()
        value = row[1].strip()
        if not value:
            continue
        if key in _TEXT_FIELDS:
            fields[_TEXT_FIELDS[key]] = value
        elif key in _FLOAT_FIELDS:
            number = _parse_number(value)
            if number is not None:
                fields[_FLOAT_FIELDS[key]] = number
    return fields


def parse_kovaaks_csv(path: str) -> TrainerSession:
    """Лог одного прогона KovaaK's.

    Бросает ValueError, если файл не похож на статистику тренажёра: молча
    отдавать пустую сессию нельзя — игрок решит, что прогон не засчитан.
    """
    blocks = _split_blocks(path)

    events: List[ShotEvent] = []
    totals: Dict[str, int] = {}
    tail: Dict[str, object] = {}
    recognised = False

    for block in blocks:
        header = _header_of(block)
        if header.startswith("kill"):
            events = _parse_kill_block(block)
            recognised = True
        elif header == "weapon":
            totals = _parse_weapon_block(block)
            recognised = True
        else:
            fields = _parse_tail_block(block)
            if fields:
                tail.update(fields)
                recognised = True

    if not recognised:
        raise ValueError(
            f"файл не похож на статистику KovaaK's: {path}; ожидались блоки "
            f"'Kill #', 'Weapon' или key:value с настройками прогона")

    return TrainerSession(
        platform="kovaaks",
        events=tuple(events),
        shots=totals.get("shots"),
        hits=totals.get("hits"),
        **tail,
    )
