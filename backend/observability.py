# -*- coding: utf-8 -*-
"""Наблюдаемость (Этап 1 запуска): Sentry по SENTRY_DSN.

Без DSN — тихий no-op: локальная разработка и тесты не требуют sentry-sdk
в рабочем состоянии. Инициализируется дважды независимо: в API (main) и
в воркере (worker) — это разные процессы.
"""
import logging
import os

logger = logging.getLogger(__name__)


def init_sentry(component: str) -> bool:
    """Включить Sentry, если задан SENTRY_DSN. component — api | worker."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "dev"),
            traces_sample_rate=float(
                os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        )
        sentry_sdk.set_tag("component", component)
        logger.info("Sentry включён (%s)", component)
        return True
    except Exception:                              # noqa: BLE001
        # Ошибка мониторинга не должна ронять продукт.
        logger.exception("Sentry не инициализировался — работаем без него")
        return False
