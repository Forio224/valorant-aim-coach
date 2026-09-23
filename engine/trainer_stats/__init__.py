# -*- coding: utf-8 -*-
"""Статистика аим-тренажёра как второй источник истины к видео.

Движок видит только геометрию: где была цель и где был прицел. Момента
выстрела в кадре нет, поэтому ни TTK, ни accuracy он посчитать не может —
это зафиксировано в docs/analysis/2026-07-15-engine-weak-spots.md.

Тренажёр пишет их сам. Клип плюс лог дают пару «вход → объективный эталон»
без ручной разметки: отсюда и метрики попаданий, и материал для evals коуча.

Лог всегда опционален. Без него модуль работает как чистый CV-путь, просто
без секции попаданий в отчёте.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

PLATFORMS = ("kovaaks", "aimbeast")


@dataclass(frozen=True)
class ShotEvent:
    """Одно событие тренажёра на временной оси прогона.

    `t_seconds` — от начала прогона, не время суток: видео и лог стартуют в
    разные моменты, и общий ноль появляется только после синхронизации.
    """
    t_seconds: float
    hit: bool
    ttk: Optional[float] = None
    target_id: Optional[str] = None


@dataclass(frozen=True)
class TrainerSession:
    """Разобранный лог одного прогона.

    Поля сводки опциональны: прогон могли прервать, а половина разбора
    полезнее отказа.
    """
    platform: str
    events: Tuple[ShotEvent, ...] = ()
    scenario: Optional[str] = None
    shots: Optional[int] = None
    hits: Optional[int] = None
    score: Optional[float] = None
    avg_ttk: Optional[float] = None
    fov: Optional[float] = None
    horiz_sens: Optional[float] = None
    sens_scale: Optional[str] = None
    resolution: Optional[str] = None

    @property
    def accuracy(self) -> Optional[float]:
        """Доля попаданий по сводке тренажёра; None, если сводки нет."""
        if self.shots is None or self.hits is None or self.shots <= 0:
            return None
        return self.hits / self.shots

    @property
    def duration_s(self) -> Optional[float]:
        if not self.events:
            return None
        return self.events[-1].t_seconds - self.events[0].t_seconds


def parse_stats(path: str, platform: str) -> TrainerSession:
    """Лог прогона по имени платформы.

    Платформа приходит с формы загрузки и уже провалидирована на границе API
    (`SUPPORTED_PLATFORMS`), поэтому неизвестное значение здесь — ошибка
    программиста, а не пользователя.
    """
    if platform == "kovaaks":
        from engine.trainer_stats.kovaaks import parse_kovaaks_csv
        return parse_kovaaks_csv(path)
    if platform == "aimbeast":
        from engine.trainer_stats.aimbeast import parse_aimbeast_stats
        return parse_aimbeast_stats(path)
    raise ValueError(
        f"нет парсера статистики для платформы {platform!r}; "
        f"поддерживаются: {', '.join(PLATFORMS)}")
