# -*- coding: utf-8 -*-
"""Общий код провайдеров коуча: нумерация кадров, base64-ресайз, подписи.

Токены картинок биллятся по пикселям (≈ ш×в/750), поэтому кадры ужимаются
по ширине перед подачей. Полноразмерные JPEG на диске не трогаем — они
нужны фронту для лайтбокса; ужимается только копия, уходящая в запрос.
"""
import base64
import io
import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

MAX_IMAGES = 10
COACH_IMAGE_MAX_WIDTH = 1024    # ниже ~800 аннотации-улики становятся нечитаемы
COACH_IMAGE_JPEG_QUALITY = 85

_FRAME_RE = re.compile(r"(\d+)")


def frame_number(path: Path) -> Optional[int]:
    """Номер кадра из имени файла вида frame_000177.jpg."""
    match = _FRAME_RE.search(path.stem)
    return int(match.group(1)) if match else None


def frame_numbers(paths: Sequence[Path]) -> List[int]:
    """Номера кадров по порядку, пропуская файлы без числа в имени."""
    return [n for n in (frame_number(p) for p in paths) if n is not None]


def frame_label(path: Path) -> str:
    """Подпись перед картинкой: 'Кадр-улика 177' или по имени файла."""
    number = frame_number(path)
    return f"Кадр-улика {number}" if number is not None else f"Кадр-улика {path.name}"


def capped_frames(frame_paths: Sequence[Path], max_images: int) -> List[Path]:
    """Первые max_images кадров — общий кап для всех провайдеров."""
    return list(frame_paths)[:max_images]


def encode_frame(path: Path) -> str:
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
