# -*- coding: utf-8 -*-
"""GET /api/v1/analysis — история разборов владельца (Этап 2, фронт).

Владелец видит только своё, гость в discord-режиме — [], off-режим отдаёт
анонимные сессии (dev), limit клампится.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager


@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.main as main

    monkeypatch.setenv("AUTH_MODE", "discord")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    db = DatabaseManager(f"sqlite:///{tmp_path / 'list.db'}")
    monkeypatch.setattr(main, "db", db)
    client = TestClient(main.app)
    return client, db


def _user(db, discord_id):
    return db.get_or_create_discord_user(
        discord_id=discord_id, username=f"u{discord_id}", avatar=None)


def _login_as(client, user):
    from backend import auth
    client.cookies.set(
        auth.SESSION_COOKIE,
        auth._encode({"sub": str(user.id)}, auth.SESSION_TTL))


def test_owner_sees_only_own_sessions_newest_first(api):
    client, db = api
    me, other = _user(db, "1"), _user(db, "2")
    first = db.create_session("a.mp4", player_id="p", clip_id="clip_a",
                              owner_user_id=me.id)
    second = db.create_session("b.mp4", player_id="p", clip_id="clip_b",
                               owner_user_id=me.id)
    db.create_session("c.mp4", player_id="p", clip_id="chuzhoi",
                      owner_user_id=other.id)
    db.create_session("d.mp4", player_id="p", clip_id="anon")

    _login_as(client, me)
    rows = client.get("/api/v1/analysis").json()
    assert [r["clip_id"] for r in rows] == ["clip_b", "clip_a"]
    assert rows[0]["session_id"] == str(second.id)
    assert rows[1]["session_id"] == str(first.id)
    assert set(rows[0]) == {"session_id", "status", "player_id", "clip_id",
                            "created_at"}


def test_guest_gets_empty_list_not_401(api):
    client, db = api
    db.create_session("a.mp4", player_id="p", clip_id="c",
                      owner_user_id=_user(db, "1").id)
    resp = client.get("/api/v1/analysis")
    assert resp.status_code == 200
    assert resp.json() == []


def test_auth_off_returns_anonymous_sessions(api, monkeypatch):
    client, db = api
    monkeypatch.setenv("AUTH_MODE", "off")
    db.create_session("a.mp4", player_id="p", clip_id="anon")
    db.create_session("b.mp4", player_id="p", clip_id="owned",
                      owner_user_id=_user(db, "1").id)
    rows = client.get("/api/v1/analysis").json()
    assert [r["clip_id"] for r in rows] == ["anon"]


def test_limit_works_and_is_clamped(api):
    client, db = api
    me = _user(db, "1")
    for i in range(5):
        db.create_session(f"{i}.mp4", player_id="p", clip_id=f"c{i}",
                          owner_user_id=me.id)
    _login_as(client, me)
    assert len(client.get("/api/v1/analysis?limit=2").json()) == 2
    # мусорные значения клампятся, а не 500
    assert len(client.get("/api/v1/analysis?limit=0").json()) == 1
    assert len(client.get("/api/v1/analysis?limit=9999").json()) == 5
