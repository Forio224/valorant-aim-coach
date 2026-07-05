# -*- coding: utf-8 -*-
"""Клиент Claude для коуча: сборка мультимодального сообщения и structured output.

Модель: env COACH_MODEL, по умолчанию claude-sonnet-5. Ретраи на 429/5xx
делает сам SDK (max_retries), отдельный retry-цикл не нужен.

Экономия токенов (коуч не измеряет, а переформулирует готовый JSON):
- thinking выключен — на Sonnet 5 без параметра включалось бы adaptive-мышление
  (лишние output-токены), а глубокое рассуждение тут не нужно;
- output_config.effort=low (env COACH_EFFORT) — терсеее и дешевле; пусто =
  не слать (модели без поддержки effort, напр. Haiku 4.5, иначе 400);
- кадры-улики ужимаются по пикселям перед подачей (токены картинки ≈ ш×в/750).
"""
import base64
import io
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Sequence

import anthropic

from coach.prompt import SYSTEM_PROMPT, build_user_text
from coach.schema import CoachReport

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "low"          # переформатирование, не рассуждение
MAX_IMAGES = 10
MAX_TOKENS = 8000
SDK_MAX_RETRIES = 4

# Кадры для коуча ужимаем по ширине: токены картинки биллятся по пикселям,
# а не по килобайтам. Полноразмерные JPEG на диске не трогаем — они нужны
# фронту для лайтбокса; ужимается только копия, уходящая в запрос.
COACH_IMAGE_MAX_WIDTH = 1024    # ниже ~800 аннотации-улики становятся нечитаемы
COACH_IMAGE_JPEG_QUALITY = 85

_FRAME_RE = re.compile(r"(\d+)")


def _frame_number(path: Path) -> Optional[int]:
    """Номер кадра из имени файла вида frame_000177.jpg."""
    match = _FRAME_RE.search(path.stem)
    return int(match.group(1)) if match else None


def _encode_frame(path: Path) -> str:
    """Base64-JPEG кадра, ужатого до COACH_IMAGE_MAX_WIDTH по ширине.

    Уже маленькие кадры и всё, что PIL не смог декодировать (битый/не-JPEG
    файл), отдаём как есть — коучинг не должен падать из-за одного кадра."""
    raw = path.read_bytes()
    try:
        from PIL import Image  # ленивый импорт: без Pillow отдаём оригинал

        with Image.open(io.BytesIO(raw)) as img:
            if img.width <= COACH_IMAGE_MAX_WIDTH:
                return base64.b64encode(raw).decode("ascii")
            height = round(img.height * COACH_IMAGE_MAX_WIDTH / img.width)
            resized = img.convert("RGB").resize(
                (COACH_IMAGE_MAX_WIDTH, height), Image.LANCZOS
            )
            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=COACH_IMAGE_JPEG_QUALITY)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — битый/не-JPEG кадр не должен ронять коуча
        logger.warning("кадр %s не ужать (битый?), отдаю оригинал", path.name)
        return base64.b64encode(raw).decode("ascii")


class CoachClient:
    """Обёртка Anthropic SDK: evidence-JSON + кадры-улики -> CoachReport."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_images: int = MAX_IMAGES,
        effort: Optional[str] = None,
    ):
        self.model = model or os.environ.get("COACH_MODEL", DEFAULT_MODEL)
        self.max_images = max_images
        # Пустая строка (env COACH_EFFORT="") = не слать effort вовсе.
        self.effort = effort if effort is not None else os.environ.get(
            "COACH_EFFORT", DEFAULT_EFFORT)
        kwargs = {"max_retries": SDK_MAX_RETRIES}
        if api_key is not None:
            kwargs["api_key"] = api_key
        self._client = anthropic.Anthropic(**kwargs)

    def build_content(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> List[dict]:
        """Контент user-сообщения: текст с JSON, затем подпись+картинка на улику.

        feedback — перечень ошибок groundedness при ретрае (Stage B2);
        добавляется финальным текстовым блоком."""
        paths = list(frame_paths)[: self.max_images]
        frame_numbers = [n for n in (_frame_number(p) for p in paths) if n is not None]
        content: List[dict] = [
            {"type": "text", "text": build_user_text(report, frame_numbers)}
        ]
        for path in paths:
            number = _frame_number(path)
            label = (
                f"Кадр-улика {number}" if number is not None else f"Кадр-улика {path.name}"
            )
            content.append({"type": "text", "text": label + ":"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": _encode_frame(path),
                    },
                }
            )
        if feedback is not None:
            content.append({"type": "text", "text": feedback})
        return content

    def generate(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> CoachReport:
        """Один вызов Claude: structured output, валидированный Pydantic-контрактом."""
        kwargs = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "disabled"},
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": self.build_content(report, frame_paths, feedback),
                }
            ],
            output_format=CoachReport,
        )
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        response = self._client.messages.parse(**kwargs)
        self._log_usage(response)
        return response.parsed_output

    @staticmethod
    def _log_usage(response) -> None:
        """Фактический расход токенов в лог — видимость для оптимизации цены."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        logger.info(
            "coach usage: input=%s output=%s cache_read=%s cache_write=%s",
            getattr(usage, "input_tokens", "?"),
            getattr(usage, "output_tokens", "?"),
            getattr(usage, "cache_read_input_tokens", 0),
            getattr(usage, "cache_creation_input_tokens", 0),
        )
