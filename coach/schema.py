# -*- coding: utf-8 -*-
"""Pydantic-контракт коучинг-отчёта.

CoachReport — то, что VLM обязан вернуть (structured output). Все числа и
кадры в тексте должны трассироваться к evidence-JSON движка; механическая
проверка — Stage B2 (coach/validate.py).
"""
from typing import List, Literal

from pydantic import BaseModel

Confidence = Literal["diagnosis", "hypothesis", "insufficient"]

Platform = Literal["kovaaks", "range", "ingame"]


class FindingExplained(BaseModel):
    """Объяснение одного finding движка со ссылками на кадры-улики."""

    metric: str
    explanation: str
    evidence_frames: List[int]
    confidence: Confidence


class Drill(BaseModel):
    """Тренировочное упражнение, привязанное к конкретному finding."""

    priority: int
    name: str
    platform: Platform
    dose: str
    target_metric: str
    success_criterion: str


class CoachReport(BaseModel):
    """Полный коучинг-отчёт: портрет, объяснения, план, ограничения."""

    summary: str
    findings_explained: List[FindingExplained]
    drills: List[Drill]
    caveats: List[str]
