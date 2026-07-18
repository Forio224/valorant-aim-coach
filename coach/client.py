# -*- coding: utf-8 -*-
"""Обратная совместимость: CoachClient переехал в coach.providers.anthropic.

Исторический путь импорта. Новый код выбирает провайдера через
coach.providers.factory.create_coach_client().
"""
from coach.providers.anthropic import (  # noqa: F401
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    MAX_IMAGES,
    CoachClient,
)
from coach.providers.common import (  # noqa: F401
    COACH_IMAGE_JPEG_QUALITY,
    COACH_IMAGE_MAX_WIDTH,
)
