# -*- coding: utf-8 -*-
"""Приватность: SteamID64 не утекает в evidence-JSON и share-выдачу.

SteamID64 — публичный идентификатор всего Steam-профиля человека; отчёт
в discord-режиме доступен гостю по share-токену. Проверка ПОДСТРОКИ на
реальном формате ответа GET — как требует спека.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager

STEAM = "76561198000000777"


@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.main as main

    monkeypatch.setenv("AUTH_MODE", "discord")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    db = DatabaseManager(f"sqlite:///{tmp_path / 'p.db'}")
    monkeypatch.setattr(main, "db", db)
    return TestClient(main.app), db


def test_get_response_and_share_never_contain_steam_id(api):
    client, db = api
    from backend import auth
    owner = db.get_or_create_discord_user(discord_id="1", username="o",
                                          avatar=None)
    db.update_user_steam_id(owner.id, STEAM)
    session = db.create_session("v.mp4", player_id="p", clip_id="c",
                                owner_user_id=owner.id)
    # отчёт с внешним блоком, как его пишет боевой analysis_task
    report = {"schema_version": "1.4",
              "external_benchmark": {"source": "kovaaks_webapp_unofficial",
                                     "season": "S5", "tiers_failed": [],
                                     "fetched_at": "x", "tiers": {}}}
    db.update_session(session.id, status="COMPLETED",
                      evidence_report=json.dumps(report),
                      external_benchmark=json.dumps(
                          report["external_benchmark"]),
                      share_token="sharetok123")

    client.cookies.set(auth.SESSION_COOKIE,
                       auth._encode({"sub": str(owner.id)}, auth.SESSION_TTL))
    owner_resp = client.get(f"/api/v1/analysis/{session.id}")
    assert owner_resp.status_code == 200
    assert STEAM not in owner_resp.text

    client.cookies.clear()
    guest = client.get(f"/api/v1/analysis/{session.id}?share=sharetok123")
    assert guest.status_code == 200
    assert STEAM not in guest.text
