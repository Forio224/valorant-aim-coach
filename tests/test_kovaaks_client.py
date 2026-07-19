# -*- coding: utf-8 -*-
"""Клиент неофициального API KovaaK's: мягкая деградация как контракт.

Сеть в тестах не трогается: http_get инжектируется. Каждый сбойный путь
обязан вернуть (None, reason) или частичный снапшот — никогда исключение.
"""
import pytest

from backend.services import kovaaks_client as kc

STEAM = "76561198000000001"

TIER_OK = {
    "overall_rank": 2,
    "benchmark_progress": 0.4,
    "categories": {
        "smoothness": {
            "scenarios": {
                "VT ww5t Novice S5": {
                    "score": 1200, "scenario_rank": 2,
                    "rank_maxes": [990, 1090, 1190, 1290],
                },
            },
        },
    },
}


@pytest.fixture(autouse=True)
def _env_and_cache(monkeypatch):
    monkeypatch.setenv(
        "KOVAAKS_S5_BENCHMARK_IDS",
        "novice=101,intermediate=102,advanced=103")
    kc._cache.clear()


def _get_ok(url, params, timeout):
    return TIER_OK


def test_success_builds_snapshot_without_steam_id():
    snap, reason = kc.fetch_benchmark_progress(STEAM, http_get=_get_ok)
    assert reason is None
    assert snap["source"] == "kovaaks_webapp_unofficial"
    assert snap["season"] == "S5"
    assert snap["tiers_failed"] == []
    assert set(snap["tiers"]) == {"novice", "intermediate", "advanced"}
    sc = snap["tiers"]["novice"]["scenarios"]["VT ww5t Novice S5"]
    assert sc["score"] == 1200 and sc["rank_maxes"] == [990, 1090, 1190, 1290]
    # приватность: steam_id в снапшоте отсутствует как подстрока
    import json
    assert STEAM not in json.dumps(snap)


def test_no_steam_id():
    assert kc.fetch_benchmark_progress(None) == (None, "no_steam_id")
    assert kc.fetch_benchmark_progress("") == (None, "no_steam_id")


def test_env_not_configured_is_api_error(monkeypatch):
    monkeypatch.delenv("KOVAAKS_S5_BENCHMARK_IDS", raising=False)
    assert kc.fetch_benchmark_progress(STEAM, http_get=_get_ok) == (
        None, "api_error")


def test_partial_failure_partial_snapshot():
    def get(url, params, timeout):
        if params["benchmarkId"] == "103":
            raise TimeoutError("budget")
        return TIER_OK
    snap, reason = kc.fetch_benchmark_progress(STEAM, http_get=get)
    assert reason is None
    assert snap["tiers_failed"] == ["advanced"]
    assert "advanced" not in snap["tiers"]
    assert "novice" in snap["tiers"]


def test_all_failed_is_api_error():
    def get(url, params, timeout):
        raise ConnectionError("down")
    assert kc.fetch_benchmark_progress(STEAM, http_get=get) == (
        None, "api_error")


def test_invalid_json_shape_is_failed_tier():
    def get(url, params, timeout):
        return {"unexpected": "shape"}
    # все три тира без сценариев -> нечего показывать -> no_scores
    assert kc.fetch_benchmark_progress(STEAM, http_get=get) == (
        None, "no_scores")


def test_all_zero_scores_is_no_scores():
    zero = {"categories": {"c": {"scenarios": {
        "S": {"score": 0, "scenario_rank": 0, "rank_maxes": [1, 2]}}}}}
    assert kc.fetch_benchmark_progress(
        STEAM, http_get=lambda u, p, t: zero) == (None, "no_scores")


def test_cache_prevents_second_network_call():
    calls = []
    def get(url, params, timeout):
        calls.append(params["benchmarkId"])
        return TIER_OK
    kc.fetch_benchmark_progress(STEAM, http_get=get)
    kc.fetch_benchmark_progress(STEAM, http_get=get)
    assert len(calls) == 3          # три тира, ОДИН раз


def test_api_error_is_not_cached():
    boom = {"n": 0}
    def get(url, params, timeout):
        boom["n"] += 1
        raise ConnectionError("down")
    kc.fetch_benchmark_progress(STEAM, http_get=get)
    kc.fetch_benchmark_progress(STEAM, http_get=get)
    assert boom["n"] == 6           # ретрай на следующем клипе разрешён
