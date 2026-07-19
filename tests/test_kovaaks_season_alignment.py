# -*- coding: utf-8 -*-
"""Сезонная сверка: kovaaks_scenario каталога существует в живом снапшоте.

Ловит дрейф имён сценариев между сезонами/правками Voltaic. Фикстура
записана с живого API (Task 9 плана); смена сезона = новые benchmarkId
(env) + имена/пороги каталога ОДНИМ коммитом.
"""
import json
from pathlib import Path

import pytest

from coach.drill_catalog import CATALOG, TIER_KEYS

FIXTURE = Path("tests/fixtures/kovaaks_s5_snapshot.json")


@pytest.mark.skipif(not FIXTURE.exists(),
                    reason="фикстура пишется вручную с живого API (Task 9)")
def test_catalog_scenarios_exist_in_live_snapshot():
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tiers = snap.get("tiers") or {}
    missing = []
    for metric, drills in CATALOG.items():
        for d in drills:
            if d.platform != "kovaaks" or d.kovaaks_scenario is None:
                continue
            scenarios = (tiers.get(TIER_KEYS[d.tier]) or {}).get(
                "scenarios") or {}
            if d.kovaaks_scenario not in scenarios:
                missing.append((d.drill_id, d.kovaaks_scenario))
    assert missing == [], (
        f"каталог разъехался с живым API: {missing}; "
        f"обнови kovaaks_scenario/rank_thresholds одним коммитом")
