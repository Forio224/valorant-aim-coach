# -*- coding: utf-8 -*-
"""Разбор статистики Aimbeast.

ВАЖНО: формат здесь не подтверждён на настоящем экспорте — в отличие от
KovaaK's, у Aimbeast он недокументирован и менялся. Поэтому парсер
толерантный: колонки ищутся по синонимам имён, время принимается и в
секундах, и временем суток, попадание — числом, словом или булевым.

Когда появится реальный файл, правкой должны оказаться списки синонимов
ниже, а не логика разбора. Если не нашлась даже колонка времени, парсер
падает с сообщением, называющим, чего не хватило: молчаливая пустая сессия
хуже отказа, потому что выглядит как «прогон не засчитан».
"""
import csv
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from engine.trainer_stats import ShotEvent, TrainerSession
from engine.trainer_stats.kovaaks import _parse_clock, _parse_number, \
    _relative_times

_TIME_KEYS = ("time", "timestamp", "t", "time (s)", "shot time", "time_s",
              "seconds", "elapsed")
_HIT_KEYS = ("hit", "result", "outcome", "is_hit", "success")
_TTK_KEYS = ("ttk", "time to kill", "time_to_kill", "killtime")
_TARGET_KEYS = ("target", "target id", "target_id", "bot", "bot id", "id")

_SCENARIO_KEYS = ("scenario", "playlist", "task", "name")
_SCORE_KEYS = ("score", "points")
_SHOTS_KEYS = ("shots", "shots fired", "total shots")
_HITS_KEYS = ("hits", "total hits")

_TRUE_WORDS = {"1", "true", "yes", "hit", "kill", "y", "t"}
_FALSE_WORDS = {"0", "false", "no", "miss", "missed", "n", "f"}


def _pick(mapping: Dict[str, Any], keys: Sequence[str]) -> Optional[Any]:
    """Первое непустое значение по любому из синонимов ключа."""
    for key in keys:
        if key in mapping:
            value = mapping[key]
            if value is not None and str(value).strip() != "":
                return value
    return None


def _normalise_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).strip().lower(): v for k, v in row.items()
            if k is not None}


def _parse_hit(value: Any) -> bool:
    """Попадание из числа, слова или булева; неизвестное значение = промах."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    number = _parse_number(text)
    return bool(number) if number is not None else False


def _parse_time(value: Any) -> Optional[float]:
    """Секунды от старта или время суток — различаются по двоеточию."""
    text = str(value).strip()
    if ":" in text:
        return _parse_clock(text)
    return _parse_number(text)


def _events_from_rows(rows: Sequence[Dict[str, Any]]) -> List[ShotEvent]:
    prepared = []
    for raw in rows:
        row = _normalise_keys(raw)
        time_value = _pick(row, _TIME_KEYS)
        if time_value is None:
            continue
        moment = _parse_time(time_value)
        if moment is None:
            continue
        hit_value = _pick(row, _HIT_KEYS)
        ttk_value = _pick(row, _TTK_KEYS)
        target_value = _pick(row, _TARGET_KEYS)
        prepared.append((
            moment,
            True if hit_value is None else _parse_hit(hit_value),
            _parse_number(str(ttk_value)) if ttk_value is not None else None,
            str(target_value).strip() if target_value is not None else None,
        ))

    if not prepared:
        return []

    # Время суток нормализуем к нулю первого события; секунды уже
    # относительные, но тот же пересчёт оставляет их как есть.
    times = _relative_times([moment for moment, _, _, _ in prepared])
    return [ShotEvent(t_seconds=t, hit=hit, ttk=ttk, target_id=target)
            for t, (_, hit, ttk, target) in zip(times, prepared)]


def _totals(events: Sequence[ShotEvent],
            summary: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Сводка тренажёра приоритетнее счёта по событиям: промахи могут не
    попадать в построчный блок, и тогда accuracy по событиям завышена."""
    shots = _pick(summary, _SHOTS_KEYS)
    hits = _pick(summary, _HITS_KEYS)
    shots_number = _parse_number(str(shots)) if shots is not None else None
    hits_number = _parse_number(str(hits)) if hits is not None else None

    if shots_number is None and events:
        shots_number = float(len(events))
    if hits_number is None and events:
        hits_number = float(sum(1 for e in events if e.hit))

    return {
        "shots": int(shots_number) if shots_number is not None else None,
        "hits": int(hits_number) if hits_number is not None else None,
    }


def _read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _read_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_aimbeast_stats(path: str) -> TrainerSession:
    """Лог одного прогона Aimbeast (CSV или JSON-экспорт)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"нет файла статистики: {path}")

    summary: Dict[str, Any] = {}
    if os.path.splitext(path)[1].lower() == ".json":
        payload = _read_json(path)
        if isinstance(payload, list):
            rows = payload
        else:
            summary = _normalise_keys(payload)
            rows = (_pick(summary, ("events", "kills", "shots_log", "log"))
                    or [])
    else:
        rows = _read_csv(path)

    events = _events_from_rows(rows)
    if not events:
        raise ValueError(
            f"не удалось найти колонку времени в статистике Aimbeast: {path}. "
            f"Ожидалась одна из: {', '.join(_TIME_KEYS)}. "
            f"Формат экспорта Aimbeast не зафиксирован — пришлите файл, "
            f"чтобы добавить его колонки в список синонимов")

    totals = _totals(events, summary)
    scenario = _pick(summary, _SCENARIO_KEYS)
    score = _pick(summary, _SCORE_KEYS)

    return TrainerSession(
        platform="aimbeast",
        events=tuple(events),
        scenario=str(scenario) if scenario is not None else None,
        score=_parse_number(str(score)) if score is not None else None,
        shots=totals["shots"],
        hits=totals["hits"],
    )
