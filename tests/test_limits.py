# -*- coding: utf-8 -*-
"""Этап 2: rate limiting по IP, дневная квота free-тира, security-заголовки."""
import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager
from backend.services.rate_limit import SlidingWindowLimiter, parse_rate


# ------------------------------------------------------------------ парсер

def test_parse_rate_units():
    assert parse_rate("20/hour") == (20, 3600.0)
    assert parse_rate("5/minute") == (5, 60.0)
    assert parse_rate("100/day") == (100, 86400.0)


def test_parse_rate_rejects_garbage():
    for bad in ("fast", "0/hour", "x/minute", "5/fortnight"):
        with pytest.raises(ValueError):
            parse_rate(bad)


def test_sliding_window_allows_then_blocks():
    limiter = SlidingWindowLimiter()
    assert limiter.allow("k", 2, 60)
    assert limiter.allow("k", 2, 60)
    assert not limiter.allow("k", 2, 60)      # третий — мимо
    assert limiter.allow("other", 2, 60)      # чужой ключ не задет


# --------------------------------------------------------------- эндпоинты

@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.main as main

    db = DatabaseManager(f"sqlite:///{tmp_path / 'lim.db'}")
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(main, "validate_clip", lambda *a, **k: None)

    def fake_pipeline(*a, **k):
        raise AssertionError("пайплайн не должен запускаться в этих тестах")

    return TestClient(main.app), db


def test_upload_rate_limit_429(api, monkeypatch):
    client, db = api
    import backend.services.rate_limit as rl
    monkeypatch.setenv("RATE_LIMIT_UPLOADS", "2/hour")
    monkeypatch.setattr(rl, "_limiter", SlidingWindowLimiter())

    def post():
        return client.post(
            "/api/v1/analysis/uploads", data={"filename": "c.mp4"})

    assert post().status_code == 200
    assert post().status_code == 200
    resp = post()
    assert resp.status_code == 429
    assert "подожд" in resp.json()["detail"].lower()


def test_rate_limit_off_by_default(api, monkeypatch):
    client, _ = api
    monkeypatch.delenv("RATE_LIMIT_UPLOADS", raising=False)
    for _ in range(30):
        assert client.post("/api/v1/analysis/uploads",
                           data={"filename": "c.mp4"}).status_code == 200


def test_daily_quota_blocks_fourth_clip(api, monkeypatch):
    client, db = api
    import backend.auth as auth
    import backend.main as main
    monkeypatch.setenv("AUTH_MODE", "discord")
    monkeypatch.setenv("SESSION_SECRET", "s")
    user = db.get_or_create_discord_user(discord_id="9", username="u",
                                         avatar=None)
    client.cookies.set(auth.SESSION_COOKIE,
                       auth._encode({"sub": str(user.id)}, auth.SESSION_TTL))
    for i in range(3):
        db.create_session(f"v{i}.mp4", player_id="p", clip_id=f"c{i}",
                          owner_user_id=user.id)

    resp = client.post(
        "/api/v1/analysis/upload",
        files={"file": ("c.mp4", b"x", "video/mp4")},
        data={"player_id": "p"})
    assert resp.status_code == 429
    assert "лимит" in resp.json()["detail"].lower()


def test_security_headers_present(api):
    client, _ = api
    resp = client.get("/healthz")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "strict-origin" in resp.headers["Referrer-Policy"]
