# -*- coding: utf-8 -*-
"""Gemini-провайдер коуча: evidence-JSON + кадры-улики -> CoachReport.

SDK google-genai (Interactions API). Structured output — по Pydantic-схеме
CoachReport (response_format с JSON-схемой), поэтому контракт и groundedness-
валидация работают без адаптации. Системный промпт кладётся первым текстовым
блоком input. Ключ — GEMINI_API_KEY из окружения/.env.
"""
import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence

from coach.prompt import SYSTEM_PROMPT, build_user_text
from coach.providers.common import (
    MAX_IMAGES,
    capped_frames,
    encode_frame,
    frame_label,
    frame_numbers,
)
from coach.schema import CoachReport

logger = logging.getLogger(__name__)

# vision + structured output + free tier; 2.5-flash закрыт для новых аккаунтов
DEFAULT_MODEL = "gemini-3.5-flash"


class GeminiCoachClient:
    """Обёртка google-genai: evidence-JSON + кадры-улики -> CoachReport."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_images: int = MAX_IMAGES,
    ):
        self.model = model or os.environ.get("COACH_MODEL", DEFAULT_MODEL)
        self.max_images = max_images
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY")
        if not key:
            raise ValueError(
                "GEMINI_API_KEY не задан — положи ключ в .env "
                "(создать: https://aistudio.google.com/apikey)"
            )
        from google import genai  # ленивый импорт: тесты подменяют _client

        self._client = genai.Client(api_key=key)

    def build_input(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> List[dict]:
        """Список блоков input: системный промпт, текст с JSON, затем на каждую
        улику подпись+картинка; feedback (ретрай) — финальным текстовым блоком."""
        paths = capped_frames(frame_paths, self.max_images)
        parts: List[dict] = [
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": build_user_text(report, frame_numbers(paths))},
        ]
        for path in paths:
            parts.append({"type": "text", "text": frame_label(path) + ":"})
            parts.append(
                {
                    "type": "image",
                    "data": encode_frame(path),
                    "mime_type": "image/jpeg",
                }
            )
        if feedback is not None:
            parts.append({"type": "text", "text": feedback})
        return parts

    def generate(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> CoachReport:
        """Один вызов Gemini: structured JSON -> Pydantic CoachReport."""
        # Interactions API, публичный kwargs-стиль: create(model=..., input=[...]).
        # Список контент-блоков SDK сам оборачивает в user_input-шаг. Ключ схемы
        # в SDK-TypedDict называется schema_ (сериализуется в 'schema').
        response = self._client.interactions.create(
            model=self.model,
            input=self.build_input(report, frame_paths, feedback),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema_": CoachReport.model_json_schema(),
            },
        )
        self._log_usage(response)
        return CoachReport.model_validate_json(response.output_text)

    @staticmethod
    def _log_usage(response) -> None:
        """Фактический расход токенов в лог — видимость для сравнения моделей."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        logger.info(
            "coach usage (gemini): input=%s output=%s thought=%s total=%s",
            getattr(usage, "total_input_tokens", "?"),
            getattr(usage, "total_output_tokens", "?"),
            getattr(usage, "total_thought_tokens", "?"),
            getattr(usage, "total_tokens", "?"),
        )
