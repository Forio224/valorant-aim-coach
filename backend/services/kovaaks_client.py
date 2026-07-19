# -*- coding: utf-8 -*-
"""Клиент неофициального веб-API KovaaK's (бенчмарки Voltaic S5).

API недокументирован (kovaaks.com/webapp-backend) — поэтому:
мягкая деградация ВСЮДУ (сбой -> «данных нет», не исключение), один
модуль на все обращения, кэш 1 ч по steam_id (вежливость к чужому API).
Кэш in-memory: при QUEUE_BACKEND=arq живёт в процессе воркера — для
одного GPU-воркера беты достаточно, при масштабировании -> Redis.
steam_id в снапшот НЕ пишется (приватность: снапшот едет в share-выдачу).
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

API_URL = ("https://kovaaks.com/webapp-backend/benchmarks/"
           "player-progress-rank-benchmark")
TIER_KEYS = ("novice", "intermediate", "advanced")
TOTAL_BUDGET_S = 6.0
CACHE_TTL_S = 3600.0

# steam_id -> (годен_до_monotonic, снапшот|None, reason|None); api_error
# не кэшируется — следующий клип имеет право на новую попытку.
_cache: Dict[str, Tuple[float, Optional[dict], Optional[str]]] = {}

HttpGet = Callable[[str, dict, float], dict]


def _default_http_get(url: str, params: dict, timeout: float) -> dict:
    import httpx

    resp = httpx.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def benchmark_ids() -> Optional[Dict[str, str]]:
    """env KOVAAKS_S5_BENCHMARK_IDS = "novice=101,intermediate=102,advanced=103".

    Сезонная ручка: смена ID сезона — без кода (имена сценариев и
    rank_thresholds каталога — кодом, одним коммитом, см. спеку)."""
    raw = os.getenv("KOVAAKS_S5_BENCHMARK_IDS", "").strip()
    if not raw:
        return None
    ids = {}
    for part in raw.split(","):
        key, _, value = part.strip().partition("=")
        if key in TIER_KEYS and value:
            ids[key] = value
    return ids if set(ids) == set(TIER_KEYS) else None


def _tier_from_payload(payload: dict) -> dict:
    """Нормализация ответа API в снапшот: берём только то, что потребляем."""
    scenarios = {}
    for cat in (payload.get("categories") or {}).values():
        for name, sc in (cat.get("scenarios") or {}).items():
            scenarios[name] = {
                "score": sc.get("score"),
                "scenario_rank": sc.get("scenario_rank"),
                "rank_maxes": sc.get("rank_maxes"),
            }
    return {"overall_rank": payload.get("overall_rank"),
            "benchmark_progress": payload.get("benchmark_progress"),
            "scenarios": scenarios}


def _has_positive_score(tiers: dict) -> bool:
    return any(
        isinstance(sc.get("score"), (int, float)) and sc["score"] > 0
        for tier in tiers.values() for sc in tier["scenarios"].values())


def fetch_benchmark_progress(
    steam_id: Optional[str], *, http_get: Optional[HttpGet] = None,
) -> Tuple[Optional[dict], Optional[str]]:
    """(снапшот, None) | (None, reason); никогда не бросает исключение."""
    if not steam_id:
        return None, "no_steam_id"
    cached = _cache.get(steam_id)
    if cached and cached[0] > time.monotonic():
        return cached[1], cached[2]

    ids = benchmark_ids()
    if ids is None:
        logger.warning("KOVAAKS_S5_BENCHMARK_IDS не настроен — внешний ранк "
                       "недоступен")
        return None, "api_error"
    get = http_get or _default_http_get

    tiers: Dict[str, dict] = {}
    failed: list = []
    deadline = time.monotonic() + TOTAL_BUDGET_S
    with ThreadPoolExecutor(max_workers=len(TIER_KEYS)) as pool:
        futures = {
            pool.submit(get, API_URL,
                        {"benchmarkId": ids[key], "steamId": steam_id,
                         "page": 0, "max": 100},
                        TOTAL_BUDGET_S): key
            for key in TIER_KEYS
        }
        try:
            for future in as_completed(
                    futures,
                    timeout=max(deadline - time.monotonic(), 0.1)):
                key = futures[future]
                try:
                    tiers[key] = _tier_from_payload(future.result())
                except Exception:          # noqa: BLE001 — деградация
                    logger.warning("kovaaks: тир %s не получен", key,
                                   exc_info=True)
                    failed.append(key)
        except Exception:                  # noqa: BLE001 — бюджет вышел
            logger.warning("kovaaks: сетевой бюджет исчерпан", exc_info=True)

    failed.extend(k for k in TIER_KEYS if k not in tiers and k not in failed)
    failed.sort(key=TIER_KEYS.index)
    if not tiers:
        return None, "api_error"           # не кэшируем: право на ретрай
    if not _has_positive_score(tiers):
        # приватный профиль неотличим от пустого — честно no_scores
        result: Tuple[Optional[dict], Optional[str]] = (None, "no_scores")
    else:
        snapshot = {
            "source": "kovaaks_webapp_unofficial",
            "fetched_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "season": "S5",
            "tiers_failed": failed,
            "tiers": tiers,
        }
        result = (snapshot, None)
    _cache[steam_id] = (time.monotonic() + CACHE_TTL_S, result[0], result[1])
    return result
