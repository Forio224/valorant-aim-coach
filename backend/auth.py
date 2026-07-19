# -*- coding: utf-8 -*-
"""Discord OAuth + сессионная кука (Этап 2 запуска).

AUTH_MODE=off (дефолт) — продукт анонимный, как в dev с самого начала.
AUTH_MODE=discord — логин обязателен для загрузки клипа; сессия — JWT в
httpOnly-куке (паролей и серверного session-store нет). Discord-клиент
инжектируется (_oauth_client) — тесты без сети.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_COOKIE = "aim_session"
SESSION_TTL = timedelta(days=30)
STATE_TTL = timedelta(minutes=10)

DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_ME_URL = "https://discord.com/api/v10/users/@me"


def auth_mode() -> str:
    return os.getenv("AUTH_MODE", "off").strip().lower()


def _secret() -> str:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        raise RuntimeError("AUTH_MODE=discord требует SESSION_SECRET")
    return secret


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000")


def _secure_cookies() -> bool:
    return os.getenv("SECURE_COOKIES", "0") == "1"


class DiscordOAuth:
    """Обмен authorization code -> профиль Discord (identify scope)."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorize_url(self, state: str) -> str:
        return DISCORD_AUTHORIZE + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "identify",
            "state": state,
        })

    async def exchange_code(self, code: str) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(DISCORD_TOKEN_URL, data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            })
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]
            me = await client.get(DISCORD_ME_URL, headers={
                "Authorization": f"Bearer {access_token}"})
            me.raise_for_status()
            data = me.json()
        return {"discord_id": data["id"],
                "username": data.get("global_name") or data["username"],
                "avatar": data.get("avatar")}


_oauth_client: Optional[DiscordOAuth] = None


def _oauth() -> DiscordOAuth:
    global _oauth_client
    if _oauth_client is None:
        client_id = os.getenv("DISCORD_CLIENT_ID")
        client_secret = os.getenv("DISCORD_CLIENT_SECRET")
        redirect_uri = os.getenv(
            "DISCORD_REDIRECT_URI",
            "http://localhost:8000/api/v1/auth/callback")
        if not client_id or not client_secret:
            raise RuntimeError(
                "AUTH_MODE=discord требует DISCORD_CLIENT_ID/SECRET")
        _oauth_client = DiscordOAuth(client_id, client_secret, redirect_uri)
    return _oauth_client


def _db():
    from backend import main
    return main.db


# ------------------------------------------------------------------ токены

def _encode(payload: dict, ttl: timedelta) -> str:
    return jwt.encode(
        {**payload, "exp": datetime.now(timezone.utc) + ttl},
        _secret(), algorithm="HS256")


def _decode(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def current_user(request: Request):
    """User из куки или None; в AUTH_MODE=off всегда None (аноним)."""
    if auth_mode() == "off":
        return None
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = _decode(token)
    if payload is None or "sub" not in payload:
        return None
    import uuid
    try:
        return _db().get_user(uuid.UUID(payload["sub"]))
    except ValueError:
        return None


def require_user(request: Request):
    """Владелец запроса; 401 в discord-режиме без логина, None в off."""
    if auth_mode() == "off":
        return None
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401,
                            detail="Нужен вход через Discord")
    return user


# --------------------------------------------------------------- эндпоинты

@router.get("/login")
async def login():
    """URL авторизации Discord; state — подписанный CSRF-токен."""
    if auth_mode() == "off":
        raise HTTPException(status_code=404, detail="Аутентификация выключена")
    state = _encode({"n": secrets.token_urlsafe(8)}, STATE_TTL)
    return {"url": _oauth().authorize_url(state)}


@router.get("/callback")
async def callback(code: str, state: str):
    if auth_mode() == "off":
        raise HTTPException(status_code=404, detail="Аутентификация выключена")
    if _decode(state) is None:
        raise HTTPException(status_code=400, detail="Некорректный state")
    try:
        info = await _oauth().exchange_code(code)
    except Exception:                              # noqa: BLE001 — лог + 502
        logger.exception("Discord: обмен кода не удался")
        raise HTTPException(status_code=502,
                            detail="Discord не ответил — попробуйте ещё раз")
    user = _db().get_or_create_discord_user(
        discord_id=info["discord_id"], username=info["username"],
        avatar=info["avatar"])
    resp = RedirectResponse(_frontend_url())
    resp.set_cookie(
        SESSION_COOKIE, _encode({"sub": str(user.id)}, SESSION_TTL),
        max_age=int(SESSION_TTL.total_seconds()), httponly=True,
        samesite="lax", secure=_secure_cookies())
    return resp


def _avatar_url(user) -> str:
    """Готовый URL аватара: фронт собрать его не может — CDN-путь требует
    discord_id, который наружу не отдаётся (и не должен)."""
    if user.avatar:
        return (f"https://cdn.discordapp.com/avatars/"
                f"{user.discord_id}/{user.avatar}.png")
    # avatar=null -> дефолтная эмбед-аватарка Discord (формула для новых
    # username-аккаунтов: (id >> 22) % 6)
    try:
        index = (int(user.discord_id) >> 22) % 6
    except ValueError:
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


@router.get("/me")
async def me(request: Request):
    """Режим + пользователь одним запросом при старте фронта."""
    user = current_user(request)
    if user is None:
        return {"mode": auth_mode(), "user": None}
    return {"mode": auth_mode(),
            "user": {"id": str(user.id), "username": user.username,
                     "avatar_url": _avatar_url(user)}}


@router.post("/logout")
async def logout():
    # Клиент — fetch: JSON вместо 303-редиректа на HTML фронта.
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp
