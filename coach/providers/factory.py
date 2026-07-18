# -*- coding: utf-8 -*-
"""Выбор провайдера коуча по COACH_PROVIDER (+ COACH_MODEL). Дефолт — gemini.

Сравнение моделей: COACH_PROVIDER/COACH_MODEL в .env для пайплайна, флаги
--provider/--model у coach_cli.py для офлайн-прогона на готовом evidence-JSON.
"""
import os
from typing import Optional

from coach.providers.anthropic import CoachClient
from coach.providers.base import CoachProvider
from coach.providers.gemini import GeminiCoachClient

DEFAULT_PROVIDER = "gemini"

_PROVIDERS = {
    "gemini": GeminiCoachClient,
    "anthropic": CoachClient,
}


def create_coach_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> CoachProvider:
    """Клиент выбранного провайдера. Неизвестный провайдер -> ValueError."""
    name = (provider or os.environ.get("COACH_PROVIDER") or DEFAULT_PROVIDER).lower()
    client_cls = _PROVIDERS.get(name)
    if client_cls is None:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ValueError(
            f"неизвестный COACH_PROVIDER '{name}'; поддерживаются: {supported}"
        )
    return client_cls(model=model)
