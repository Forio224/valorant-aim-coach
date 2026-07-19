# -*- coding: utf-8 -*-
"""Приём SteamID64: механическая валидация до сети, хранение на аккаунте.

steam_id — самоотчёт уровня sens/eDPI; в discord-режиме сохраняется на
аккаунт и предзаполняется, в off-режиме живёт только в форме.
"""
import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager


@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.main as main

    monkeypatch.setenv("AUTH_MODE", "discord")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    db = DatabaseManager(f"sqlite:///{tmp_path / 's.db'}")
    monkeypatch.setattr(main, "db", db)
    # пайплайн не нужен: валидация срабатывает до постановки в очередь
    return TestClient(main.app), db


def _login(client, db):
    from backend import auth
    user = db.get_or_create_discord_user(
        discord_id="42", username="u", avatar=None)
    client.cookies.set(
        auth.SESSION_COOKIE,
        auth._encode({"sub": str(user.id)}, auth.SESSION_TTL))
    return user


def test_bad_steam_id_is_422_before_upload(api):
    client, db = api
    _login(client, db)
    resp = client.post(
        "/api/v1/analysis/upload",
        files={"file": ("c.mp4", b"x", "video/mp4")},
        data={"player_id": "p", "steam_id": "not-a-steam-id"})
    assert resp.status_code == 422
    assert "17 цифр" in resp.json()["detail"]


def test_valid_steam_id_saved_to_account(api, monkeypatch):
    client, db = api
    user = _login(client, db)
    # мусорное видео срежется валидацией клипа ПОСЛЕ steam_id —
    # подменяем validate_clip, чтобы дойти до сохранения
    import backend.main as main
    monkeypatch.setattr(main, "validate_clip", lambda p: None)
    called = {}
    async def fake_enqueue(bt, job):
        called["job"] = job
    monkeypatch.setattr(main.job_queue, "enqueue", fake_enqueue)
    resp = client.post(
        "/api/v1/analysis/upload",
        files={"file": ("c.mp4", b"x", "video/mp4")},
        data={"player_id": "p", "steam_id": "76561198000000001"})
    assert resp.status_code == 200
    assert called["job"].steam_id == "76561198000000001"
    assert db.get_user(user.id).steam_id == "76561198000000001"


def test_me_returns_saved_steam_id(api):
    client, db = api
    user = _login(client, db)
    db.update_user_steam_id(user.id, "76561198000000001")
    assert (client.get("/api/v1/auth/me").json()["user"]["steam_id"]
            == "76561198000000001")


def test_logged_in_without_form_value_uses_account_id(api, monkeypatch):
    client, db = api
    user = _login(client, db)
    db.update_user_steam_id(user.id, "76561198000000009")
    import backend.main as main
    monkeypatch.setattr(main, "validate_clip", lambda p: None)
    called = {}
    async def fake_enqueue(bt, job):
        called["job"] = job
    monkeypatch.setattr(main.job_queue, "enqueue", fake_enqueue)
    client.post(
        "/api/v1/analysis/upload",
        files={"file": ("c.mp4", b"x", "video/mp4")},
        data={"player_id": "p"})
    assert called["job"].steam_id == "76561198000000009"


def test_job_payload_roundtrip_keeps_steam_id():
    from backend.services.analysis_task import AnalysisJob
    job = AnalysisJob(session_id="s", video_path="v", player_id="p",
                      clip_id="c", steam_id="76561198000000001")
    assert AnalysisJob.from_payload(job.to_payload()).steam_id == (
        "76561198000000001")
