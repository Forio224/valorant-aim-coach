# -*- coding: utf-8 -*-
"""Этап 2: Discord OAuth + сессионная кука.

AUTH_MODE=off (дефолт) — всё анонимно, как раньше. AUTH_MODE=discord —
логин обязателен для загрузки. Discord подменяется фейком: проверяем
state-CSRF, upsert пользователя, куку и /auth/me.
"""
import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager


class FakeDiscord:
    """Контракт auth.DiscordOAuth без сети."""

    def __init__(self, avatar="abc"):
        self.exchanged = []
        self.avatar = avatar

    def authorize_url(self, state: str) -> str:
        return f"https://discord.com/oauth2/authorize?state={state}"

    async def exchange_code(self, code: str) -> dict:
        self.exchanged.append(code)
        return {"discord_id": "111222333", "username": "shooter",
                "avatar": self.avatar}


@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.auth as auth
    import backend.main as main

    monkeypatch.setenv("AUTH_MODE", "discord")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    db = DatabaseManager(f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setattr(main, "db", db)
    fake = FakeDiscord()
    monkeypatch.setattr(auth, "_oauth_client", fake)
    client = TestClient(main.app)
    return client, db, fake, auth


def _login(client, auth_module):
    """Полный проход login->callback; возвращает ответ callback."""
    url = client.get("/api/v1/auth/login").json()["url"]
    state = url.split("state=")[1]
    return client.get(f"/api/v1/auth/callback?code=c1&state={state}",
                      follow_redirects=False)


def test_login_returns_discord_url_with_state(api):
    client, *_ = api
    resp = client.get("/api/v1/auth/login")
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://discord.com/")


def test_callback_creates_user_sets_cookie_and_redirects(api):
    client, db, fake, auth = api
    resp = _login(client, auth)
    assert resp.status_code == 307
    assert resp.headers["location"] == "http://localhost:3000"
    assert "aim_session" in resp.cookies
    assert fake.exchanged == ["c1"]

    me = client.get("/api/v1/auth/me").json()
    assert me["user"]["username"] == "shooter"


def test_callback_rejects_forged_state(api):
    client, *_ = api
    resp = client.get("/api/v1/auth/callback?code=c1&state=forged",
                      follow_redirects=False)
    assert resp.status_code == 400


def test_repeat_login_upserts_same_user(api):
    client, db, fake, auth = api
    _login(client, auth)
    _login(client, auth)
    from sqlmodel import Session, select

    from backend.database import User
    with Session(db.engine) as s:
        users = s.exec(select(User)).all()
    assert len(users) == 1
    assert users[0].discord_id == "111222333"


def test_me_anonymous_is_null(api):
    client, *_ = api
    client.cookies.clear()
    assert client.get("/api/v1/auth/me").json() == {
        "mode": "discord", "user": None}


def test_me_mode_off(monkeypatch):
    import backend.main as main
    monkeypatch.delenv("AUTH_MODE", raising=False)
    client = TestClient(main.app)
    assert client.get("/api/v1/auth/me").json() == {"mode": "off",
                                                    "user": None}


def test_me_returns_ready_avatar_url(api):
    client, db, fake, auth = api
    _login(client, auth)
    user = client.get("/api/v1/auth/me").json()["user"]
    # URL собирает сервер: фронту discord_id не отдаётся
    assert user["avatar_url"] == (
        "https://cdn.discordapp.com/avatars/111222333/abc.png")
    assert "avatar" not in user and "discord_id" not in user


def test_me_null_avatar_falls_back_to_embed(api):
    client, db, fake, auth = api
    fake.avatar = None
    _login(client, auth)
    user = client.get("/api/v1/auth/me").json()["user"]
    index = (111222333 >> 22) % 6
    assert user["avatar_url"] == (
        f"https://cdn.discordapp.com/embed/avatars/{index}.png")


def test_logout_returns_json_and_clears_cookie(api):
    client, db, fake, auth = api
    _login(client, auth)
    resp = client.post("/api/v1/auth/logout")
    # Клиент — fetch: JSON, а не 303-редирект на HTML фронта
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert client.get("/api/v1/auth/me").json()["user"] is None


def test_upload_requires_login_when_auth_on(api, tmp_path):
    client, *_ = api
    client.cookies.clear()
    resp = client.post(
        "/api/v1/analysis/upload",
        files={"file": ("c.mp4", b"x", "video/mp4")},
        data={"player_id": "p"})
    assert resp.status_code == 401


def test_auth_off_keeps_anonymous_upload(tmp_path, monkeypatch):
    # Дефолтный dev-режим: без логина, поведение прежнее (см. test_backend_api)
    import backend.auth as auth
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert auth.auth_mode() == "off"
