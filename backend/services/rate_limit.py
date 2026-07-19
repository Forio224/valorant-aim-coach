# -*- coding: utf-8 -*-
"""Rate limiting загрузок (Этап 2 запуска). Без внешних зависимостей.

Скользящее окно в памяти процесса: для одного API-инстанса беты этого
достаточно; при горизонтальном масштабировании перенести на Redis.
RATE_LIMIT_UPLOADS: "20/hour", "5/minute", "100/day" или "off" (дефолт
dev; на проде включить). Ключ — IP клиента (до логина другого нет).
"""
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request

_WINDOWS = {"second": 1.0, "minute": 60.0, "hour": 3600.0, "day": 86400.0}


def parse_rate(spec: str) -> Tuple[int, float]:
    """"20/hour" -> (20, 3600.0); ValueError на мусор в конфиге."""
    try:
        count_raw, unit = spec.strip().split("/")
        count = int(count_raw)
        window = _WINDOWS[unit.strip().lower()]
    except (ValueError, KeyError):
        raise ValueError(
            f"RATE_LIMIT: {spec!r} — ожидается вид '20/hour' "
            f"({'|'.join(_WINDOWS)})")
    if count <= 0:
        raise ValueError(f"RATE_LIMIT: {spec!r} — счётчик должен быть > 0")
    return count, window


class SlidingWindowLimiter:
    def __init__(self):
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, count: int, window_s: float) -> bool:
        now = time.monotonic()
        events = self._events[key]
        while events and events[0] <= now - window_s:
            events.popleft()
        if len(events) >= count:
            return False
        events.append(now)
        return True


_limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:                          # за прокси (Fly/Railway)
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_upload_limit(request: Request) -> None:
    """429 при превышении лимита загрузок с одного IP."""
    spec = os.getenv("RATE_LIMIT_UPLOADS", "off").strip().lower()
    if spec in ("off", ""):
        return
    count, window = parse_rate(spec)
    if not _limiter.allow(f"uploads:{client_ip(request)}", count, window):
        raise HTTPException(
            status_code=429,
            detail="Слишком много загрузок подряд — подождите немного и "
                   "попробуйте снова.")
