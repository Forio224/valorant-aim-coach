# -*- coding: utf-8 -*-
"""Этап 2: отчёт видит только владелец; шеринг — по явному share-токену.

Дыра до этого: любой, кто узнал UUID сессии, читал чужой отчёт. Сессии
анонимной эпохи (owner IS NULL) остаются открытыми — обратная
совместимость dev-режима.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager


@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.auth as auth
    import backend.main as main

    monkeypatch.setenv("AUTH_MODE", "discord")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    db = DatabaseManager(f"sqlite:///{tmp_path / 'own.db'}")
    monkeypatch.setattr(main, "db", db)
    return TestClient(main.app), db, auth


def _user(db, discord_id="1"):
    return db.get_or_create_discord_user(
        discord_id=discord_id, username=f"u{discord_id}", avatar=None)


def _login_as(client, auth, user):
    token = auth._encode({"sub": str(user.id)}, auth.SESSION_TTL)
    client.cookies.set(auth.SESSION_COOKIE, token)


def test_owner_reads_own_session(api):
    client, db, auth = api
    owner = _user(db)
    s = db.create_session("v.mp4", player_id="p", clip_id="c",
                          owner_user_id=owner.id)
    _login_as(client, auth, owner)
    resp = client.get(f"/api/v1/analysis/{s.id}")
    assert resp.status_code == 200
    assert resp.json()["is_owner"] is True


def test_stranger_gets_404_not_403(api):
    # 404, а не 403: не подтверждаем существование чужой сессии
    client, db, auth = api
    owner, stranger = _user(db, "1"), _user(db, "2")
    s = db.create_session("v.mp4", player_id="p", clip_id="c",
                          owner_user_id=owner.id)
    _login_as(client, auth, stranger)
    assert client.get(f"/api/v1/analysis/{s.id}").status_code == 404


def test_anonymous_gets_404_for_owned_session(api):
    client, db, auth = api
    owner = _user(db)
    s = db.create_session("v.mp4", player_id="p", clip_id="c",
                          owner_user_id=owner.id)
    assert client.get(f"/api/v1/analysis/{s.id}").status_code == 404


def test_share_token_opens_session_for_anyone(api):
    client, db, auth = api
    owner = _user(db)
    s = db.create_session("v.mp4", player_id="p", clip_id="c",
                          owner_user_id=owner.id)
    _login_as(client, auth, owner)
    token = client.post(f"/api/v1/analysis/{s.id}/share").json()["share_token"]

    client.cookies.clear()
    ok = client.get(f"/api/v1/analysis/{s.id}?share={token}")
    assert ok.status_code == 200
    assert ok.json()["is_owner"] is False
    assert client.get(
        f"/api/v1/analysis/{s.id}?share=wrong").status_code == 404


def test_share_is_idempotent_and_owner_only(api):
    client, db, auth = api
    owner, stranger = _user(db, "1"), _user(db, "2")
    s = db.create_session("v.mp4", player_id="p", clip_id="c",
                          owner_user_id=owner.id)
    _login_as(client, auth, owner)
    t1 = client.post(f"/api/v1/analysis/{s.id}/share").json()["share_token"]
    t2 = client.post(f"/api/v1/analysis/{s.id}/share").json()["share_token"]
    assert t1 == t2                       # ссылка стабильна, не плодим токены

    _login_as(client, auth, stranger)
    assert client.post(f"/api/v1/analysis/{s.id}/share").status_code == 404


def test_legacy_anonymous_session_stays_open(api):
    client, db, auth = api
    s = db.create_session("v.mp4", player_id="p", clip_id="c")
    assert client.get(f"/api/v1/analysis/{s.id}").status_code == 200


def test_history_is_scoped_to_owner(api):
    # «friend» у двух аккаунтов — разные люди: история не смешивается
    client, db, auth = api
    u1, u2 = _user(db, "1"), _user(db, "2")
    db.create_session("a.mp4", player_id="friend", clip_id="a",
                      owner_user_id=u1.id)
    db.create_session("b.mp4", player_id="friend", clip_id="b",
                      owner_user_id=u2.id)
    db.create_session("c.mp4", player_id="friend", clip_id="c")

    assert [r.clip_id for r in db.list_sessions_for_player(
        "friend", owner_user_id=u1.id)] == ["a"]
    assert [r.clip_id for r in db.list_sessions_for_player(
        "friend", owner_user_id=None)] == ["c"]


def test_owner_response_includes_share_token(api):
    client, db, auth = api
    owner = _user(db)
    s = db.create_session("v.mp4", player_id="p", clip_id="c",
                          owner_user_id=owner.id)
    _login_as(client, auth, owner)
    client.post(f"/api/v1/analysis/{s.id}/share")
    body = client.get(f"/api/v1/analysis/{s.id}").json()
    assert body["share_token"]            # владелец видит токен для кнопки

    client.cookies.clear()
    shared = client.get(
        f"/api/v1/analysis/{s.id}?share={body['share_token']}").json()
    assert shared["share_token"] is None  # гостю токен не отдаём
