# -*- coding: utf-8 -*-
"""Pydantic-контракт коучинг-отчёта.

CoachReport — то, что VLM обязан вернуть (structured output). Все числа и
кадры в тексте должны трассироваться к evidence-JSON движка; механическая
проверка — Stage B2 (coach/validate.py).
"""
from typing import List, Literal, Optional

from pydantic import BaseModel

Confidence = Literal["diagnosis", "hypothesis", "insufficient"]

Platform = Literal["kovaaks", "range", "ingame"]


class FindingExplained(BaseModel):
    """Объяснение одного finding движка со ссылками на кадры-улики."""

    metric: str
    explanation: str
    evidence_frames: List[int]
    confidence: Confidence


class ProgressExplained(BaseModel):
    """Объяснение динамики одной метрики. direction — enum, матчится валидатором
    == engine.direction; человеческая формулировка — в explanation."""

    metric: str
    direction: Literal["improved", "regressed", "flat"]
    confidence: Confidence
    explanation: str


class DrillSelection(BaseModel):
    """Выбор VLM: id упражнения из каталога движка + приоритет + обоснование.

    VLM НЕ производит ни названий, ни чисел — их детерминированно
    подставляет движок (coach/drill_catalog.py) после валидации."""

    priority: int
    drill_id: str
    rationale: str


class SuccessCriterion(BaseModel):
    """Числовой критерий успеха, посчитанный движком из values finding-а.

    Строка `text` — для UI; остальные поля структурны для машинной сверки
    на следующем клипе (Фаза 2)."""

    metric: str
    value_key: str
    comparator: str            # "<" | "count_le" | "direction"
    target: Optional[float]
    baseline: Optional[float]
    text: str


class Drill(BaseModel):
    """Финальный дрилл, собранный движком из DrillSelection + каталога."""

    priority: int
    drill_id: str
    name: str
    platform: Platform
    tier: int
    dose: str
    target_metric: str
    rationale: str
    success_criterion: str
    criterion: SuccessCriterion


class CoachReport(BaseModel):
    """Коучинг-отчёт: портрет, объяснения, ВЫБОР дриллов, ограничения.

    drills — сырой выбор VLM (DrillSelection); финальные Drill подставляет
    движок после сборки и не участвуют в structured output контракте.
    progress_explained — динамика метрик по истории (Фаза 2B), заземляется
    валидатором против engine drill_progress."""

    summary: str
    findings_explained: List[FindingExplained]
    drills: List[DrillSelection]
    caveats: List[str]
    progress_explained: List[ProgressExplained] = []
