# KovaaK's External Rank (Voltaic S5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Автоподтяжка ранга и посценарных скоров Voltaic S5 из неофициального
API kovaaks.com по SteamID64 игрока: механический гейт тира дриллов, факты
для коуча под groundedness-валидацией, строка внешнего ранга на фронте.

**Architecture:** Один HTTP-клиент (`backend/services/kovaaks_client.py`) с
кэшем и мягкой деградацией; снапшот едет через пайплайн в evidence-JSON
(schema 1.4) и в JSON-колонку сессии; каталог дриллов получает
`kovaaks_scenario` и внешний гейт тира; валидатор заземляет внешние числа
тем же коммитом, что открывает их коучу. Спека:
`docs/superpowers/specs/2026-07-19-kovaaks-external-rank-design.md` (одобрена).

**Tech Stack:** FastAPI + SQLModel + Alembic, httpx (sync, уже в зависимостях
через auth), React 18 (CRA) + RTL, pytest.

## Global Constraints

- Любой сбой клиента → «данных нет», НИКОГДА не FAILED (мягкая деградация).
- Перечень `external_unavailable_reason`: `"no_steam_id" | "api_error" |
  "no_scores"` — ровно три, private-профиль = `no_scores`.
- steam_id НЕ попадает в снапшот / evidence-JSON / share-выдачу (приватность).
- Снапшот: `source="kovaaks_webapp_unofficial"`, `season="S5"`,
  `tiers_failed`, `tiers.{novice|intermediate|advanced}`.
- Верхний порог тира = `max(rank_maxes)` из снапшота; фолбэк —
  `max(rank_thresholds.values())` каталога. Коуч видит РОВНО числа гейта.
- Гейт тира действует ТОЛЬКО на kovaaks-дриллы; ingame/range остаются tier 1.
- Отсутствующий в снапшоте тир ничего не открывает.
- Нет блока = поведение как сегодня (регресс-инвариант, закреплён тестами).
- SCHEMA_VERSION 1.3 → 1.4 ТЕМ ЖЕ коммитом, что вводит новые поля отчёта
  (Task 3); расширение валидатора — тем же коммитом, что открывает числа
  коучу (Task 6 и Task 7 коммитятся вместе, см. Task 7 шаг 6).
- Общий сетевой бюджет клиента 6 с на три параллельных запроса; кэш 1 ч
  in-memory по steam_id (api_error не кэшируется).
- Запуск тестов: `.\.venv\Scripts\python.exe -m pytest <файл> -q` из корня;
  фронт: `cd frontend; $env:CI="true"; npx react-scripts test --watchAll=false`.
- Коммиты БЕЗ trailer'а Co-Authored-By.

---

### Task 1: HTTP-клиент kovaaks_client с кэшем и деградацией

**Files:**
- Create: `backend/services/kovaaks_client.py`
- Create: `tests/test_kovaaks_client.py`
- Modify: `.env.example` (блок «Внешний ранк KovaaK's»)

**Interfaces:**
- Produces: `fetch_benchmark_progress(steam_id: Optional[str], *, http_get=None)
  -> tuple[Optional[dict], Optional[str]]` — `(снапшот, None)` либо
  `(None, reason)`. Снапшот — dict формата спеки (без steam_id!).
  `TIER_KEYS = ("novice", "intermediate", "advanced")`. Для тестов:
  инжектируемый `http_get(url: str, params: dict, timeout: float) -> dict`
  (возвращает распарсенный JSON или бросает исключение) и `_cache.clear()`.

- [ ] **Step 1: Написать падающие тесты клиента**

```python
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
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_kovaaks_client.py -q`
Expected: FAIL / ERROR c `ModuleNotFoundError: backend.services.kovaaks_client`

- [ ] **Step 3: Реализовать клиент**

```python
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
        for future in as_completed(futures,
                                   timeout=max(deadline - time.monotonic(),
                                               0.1)):
            key = futures[future]
            try:
                tiers[key] = _tier_from_payload(future.result())
            except Exception:              # noqa: BLE001 — деградация
                logger.warning("kovaaks: тир %s не получен", key,
                               exc_info=True)
                failed.append(key)

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
```

Замечание для исполнителя: `as_completed(..., timeout=...)` бросает
`TimeoutError`, если бюджет вышел до завершения всех фьючерсов — оберни цикл
`for future in as_completed(...)` в `try/except Exception`, недошедшие тиры
попадут в `failed` строкой ниже. Это часть контракта «никогда не бросает».

- [ ] **Step 4: Прогнать тесты клиента**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_kovaaks_client.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Дописать .env.example**

После блока «Коуч» добавить:

```
# --- Внешний ранк KovaaK's (Voltaic S5) ---
# benchmarkId трёх тиров S5 в веб-приложении kovaaks.com. Найти: открыть
# kovaaks.com/kovaaks/benchmark-tracker -> выбрать Voltaic S5 -> в DevTools
# (Network) запрос player-progress-rank-benchmark?benchmarkId=NNN.
# Не настроено -> внешний ранк молча недоступен (reason=api_error).
# KOVAAKS_S5_BENCHMARK_IDS=novice=101,intermediate=102,advanced=103
```

- [ ] **Step 6: Commit**

```powershell
git add backend/services/kovaaks_client.py tests/test_kovaaks_client.py .env.example
git commit -m "feat(backend): клиент неофициального API KovaaK's — снапшот S5 с кэшем и мягкой деградацией"
```

---

### Task 2: Приём steam_id — форма, аккаунт, очередь

**Files:**
- Modify: `backend/database.py` (User.steam_id, AnalysisSession.external_benchmark, метод update_user_steam_id)
- Create: `migrations/versions/0003_steam_id_external_benchmark.py`
- Modify: `backend/main.py` (Form-поле в /upload и /start, валидация, сохранение на аккаунт)
- Modify: `backend/auth.py` (`/me` отдаёт steam_id владельцу)
- Modify: `backend/services/analysis_task.py` (AnalysisJob.steam_id)
- Test: `tests/test_steam_id_intake.py`

**Interfaces:**
- Consumes: ничего из Task 1 (независим).
- Produces: `AnalysisJob.steam_id: Optional[str]` (в payload очереди);
  `User.steam_id`; `AnalysisSession.external_benchmark: Optional[str]`
  (JSON-колонка, наполняется в Task 4); `/me.user.steam_id`;
  422 на невалидный SteamID64.

- [ ] **Step 1: Написать падающие тесты**

```python
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
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_steam_id_intake.py -q`
Expected: FAIL (`unexpected keyword argument 'steam_id'`, 400 вместо 422 и т.п.)

- [ ] **Step 3: database.py — колонки и метод**

В `class User` после `avatar`:

```python
    steam_id: Optional[str] = None     # SteamID64 (внешний ранк KovaaK's)
```

В `class AnalysisSession` после `evidence_frames`:

```python
    external_benchmark: Optional[str] = None  # JSON-снапшот KovaaK's S5
```

В `DatabaseManager` после `get_user`:

```python
    def update_user_steam_id(self, user_id: UUID,
                             steam_id: Optional[str]) -> None:
        with Session(self.engine) as session:
            user = session.get(User, user_id)
            if user is not None:
                user.steam_id = steam_id
                session.add(user)
                session.commit()
```

- [ ] **Step 4: Миграция 0003 (по образцу 0002)**

```python
# -*- coding: utf-8 -*-
"""SteamID64 на аккаунте + снапшот внешнего бенчмарка на сессии.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("steam_id", sa.String(), nullable=True))
    op.add_column("analysissession",
                  sa.Column("external_benchmark", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysissession", "external_benchmark")
    op.drop_column("user", "steam_id")
```

- [ ] **Step 5: main.py — Form-поле, валидация, сохранение**

Рядом с `ALLOWED_EXTENSIONS` (используется в обоих путях загрузки):

```python
import re

STEAM_ID_RE = re.compile(r"^\d{17}$")


def _resolve_steam_id(form_value: str | None, user) -> str | None:
    """Механическая валидация SteamID64 (мусор до сети не доходит) +
    сохранение на аккаунт: один раз ввёл — дальше подставляется."""
    steam_id = (form_value or "").strip() or None
    if steam_id is not None and not STEAM_ID_RE.fullmatch(steam_id):
        raise HTTPException(
            status_code=422,
            detail="SteamID64 — это 17 цифр (например 76561198000000001); "
                   "найти свой: steamid.io или URL профиля Steam.")
    if steam_id is None and user is not None:
        return user.steam_id
    if steam_id is not None and user is not None and user.steam_id != steam_id:
        db.update_user_steam_id(user.id, steam_id)
    return steam_id
```

В `upload_video` и `start_analysis`: добавить параметр
`steam_id: str | None = Form(None)`, после `_validate_upload_meta(...)`
вставить `steam_id = _resolve_steam_id(steam_id, user)` и передать
`steam_id=steam_id` в `_create_and_enqueue`. В `_create_and_enqueue` добавить
параметр `steam_id=None` и поле `steam_id=steam_id` в `AnalysisJob(...)`.

- [ ] **Step 6: analysis_task.py — AnalysisJob.steam_id**

В dataclass после `owner_id`:

```python
    steam_id: Optional[str] = None     # SteamID64 -> внешний ранк KovaaK's
```

В `to_payload()` добавить `"steam_id": self.steam_id`.

- [ ] **Step 7: auth.py — /me отдаёт steam_id владельцу**

В `me()` в dict пользователя добавить `"steam_id": user.steam_id`
(это данные самого владельца; в чужие руки /me не попадает).

- [ ] **Step 8: Прогнать тесты**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_steam_id_intake.py tests/test_auth.py -q`
Expected: PASS (существующие auth-тесты не сломаны: сравнение в
`test_me_returns_ready_avatar_url` использует точечные ключи, но
`set(rows[0])`-подобных assert'ов на user-dict нет)

- [ ] **Step 9: Commit**

```powershell
git add backend/database.py backend/main.py backend/auth.py backend/services/analysis_task.py migrations/versions/0003_steam_id_external_benchmark.py tests/test_steam_id_intake.py
git commit -m "feat(backend): приём SteamID64 — валидация 422, хранение на аккаунте, поле очереди"
```

---

### Task 3: Блок external_benchmark в evidence-JSON (schema 1.4)

**Files:**
- Modify: `engine/report.py:37` (SCHEMA_VERSION), `build_report` (строки 320–357)
- Test: `tests/test_report.py` (дописать класс тестов)

**Interfaces:**
- Consumes: формат снапшота из Task 1 (движок его НЕ строит — получает готовым).
- Produces: `build_report(..., external_benchmark: Optional[dict] = None,
  external_unavailable_reason: Optional[str] = None)`; в отчёте top-level
  `external_benchmark` (dict) ЛИБО `external_unavailable_reason` (str,
  default `"no_steam_id"`); `SCHEMA_VERSION == "1.4"`.

- [ ] **Step 1: Написать падающие тесты (дописать в tests/test_report.py)**

```python
# --- Внешний ранк KovaaK's (schema 1.4) --------------------------------------

EXTERNAL_SNAPSHOT = {
    "source": "kovaaks_webapp_unofficial", "fetched_at": "2026-07-19T00:00:00+00:00",
    "season": "S5", "tiers_failed": [],
    "tiers": {"novice": {"overall_rank": 2, "benchmark_progress": 0.4,
                         "scenarios": {"VT ww5t Novice S5": {
                             "score": 1200, "scenario_rank": 2,
                             "rank_maxes": [990, 1090, 1190, 1290]}}}},
}


def test_report_carries_external_benchmark_block():
    ctx = _ctx()                       # использовать хелпер контекста этого файла
    report = build_report(ctx, [], [], external_benchmark=EXTERNAL_SNAPSHOT)
    assert report["schema_version"] == "1.4"
    assert report["external_benchmark"] == EXTERNAL_SNAPSHOT
    assert "external_unavailable_reason" not in report


def test_report_without_block_names_reason():
    ctx = _ctx()
    report = build_report(ctx, [], [],
                          external_unavailable_reason="api_error")
    assert report["external_unavailable_reason"] == "api_error"
    assert "external_benchmark" not in report


def test_report_default_reason_is_no_steam_id():
    ctx = _ctx()
    report = build_report(ctx, [], [])
    assert report["external_unavailable_reason"] == "no_steam_id"
```

Примечание исполнителю: `_ctx()` — взять существующий способ построения
`ClipContext` из tests/test_report.py (там уже есть фабрика/фикстура для
`build_report`-тестов; переиспользовать её, не изобретать новую).

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_report.py -q -k external`
Expected: FAIL (`unexpected keyword argument 'external_benchmark'`)

- [ ] **Step 3: Реализовать в report.py**

`SCHEMA_VERSION = "1.4"` (строка 37). Сигнатура `build_report` — добавить
после `attribution`:

```python
                 external_benchmark: Optional[dict] = None,
                 external_unavailable_reason: Optional[str] = None) -> dict:
```

После строки `report["target_choices"] = ...` вставить:

```python
    # Внешний ранк KovaaK's (schema 1.4): чужие измерения, не наши — движок
    # блок не строит и не пересчитывает, только переносит. Контракт на
    # отсутствие: у отчёта ВСЕГДА есть ровно одно из двух полей.
    if external_benchmark is not None:
        report["external_benchmark"] = external_benchmark
    else:
        report["external_unavailable_reason"] = (
            external_unavailable_reason or "no_steam_id")
```

- [ ] **Step 4: Прогнать тесты отчёта**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_report.py -q`
Expected: PASS (кроме до-веточного `test_report_on_real_clip_is_fully_evidenced`,
падающего из-за отсутствия dataset1 локально — см. Global Constraints)

- [ ] **Step 5: Commit**

```powershell
git add engine/report.py tests/test_report.py
git commit -m "feat(engine): external_benchmark в evidence-JSON — schema 1.4, контракт отсутствия"
```

---

### Task 4: Проводка через пайплайн + приватность share-выдачи

**Files:**
- Modify: `backend/services/analysis_pipeline.py` (`run_pipeline`: параметры steam_id/external_fetcher, вызов на MEASURING)
- Modify: `backend/services/analysis_task.py` (передать job.steam_id; персист колонки external_benchmark)
- Test: `tests/test_analysis_pipeline.py` (дописать), `tests/test_privacy_steam_id.py` (создать)

**Interfaces:**
- Consumes: `fetch_benchmark_progress` (Task 1), `build_report(...,
  external_benchmark=, external_unavailable_reason=)` (Task 3),
  `AnalysisJob.steam_id` (Task 2).
- Produces: `run_pipeline(..., steam_id: Optional[str] = None,
  external_fetcher: Optional[Callable] = None)`; сессия получает колонку
  `external_benchmark` (JSON или NULL).

- [ ] **Step 1: Падающие тесты пайплайна (дописать в tests/test_analysis_pipeline.py)**

```python
def test_external_fetcher_failure_never_fails_session(tmp_path):
    """Спека: любой сбой клиента -> COMPLETED без блока, не FAILED."""
    def exploding_fetcher(steam_id):
        raise RuntimeError("api down hard")
    result = run_pipeline(
        str(_make_video(tmp_path)), "p",           # хелперы файла
        evidence_dir=str(tmp_path / "ev"),
        detector=lambda path: {},                   # пустой клип — без коуча
        steam_id="76561198000000001",
        external_fetcher=exploding_fetcher)
    assert result.evidence_report["external_unavailable_reason"] == "api_error"


def test_external_snapshot_lands_in_report(tmp_path):
    snap = {"source": "kovaaks_webapp_unofficial", "season": "S5",
            "fetched_at": "x", "tiers_failed": [], "tiers": {}}
    result = run_pipeline(
        str(_make_video(tmp_path)), "p",
        evidence_dir=str(tmp_path / "ev"),
        detector=lambda path: {},
        steam_id="76561198000000001",
        external_fetcher=lambda sid: (snap, None))
    assert result.evidence_report["external_benchmark"] == snap


def test_no_steam_id_skips_fetcher_entirely(tmp_path):
    calls = []
    result = run_pipeline(
        str(_make_video(tmp_path)), "p",
        evidence_dir=str(tmp_path / "ev"),
        detector=lambda path: {},
        external_fetcher=lambda sid: calls.append(sid) or (None, "api_error"))
    assert calls == []
    assert result.evidence_report["external_unavailable_reason"] == "no_steam_id"
```

Примечание: `_make_video` — существующий хелпер синтетического видео в этом
файле тестов; переиспользовать.

- [ ] **Step 2: Падающий тест приватности (tests/test_privacy_steam_id.py)**

```python
# -*- coding: utf-8 -*-
"""Приватность: SteamID64 не утекает в evidence-JSON и share-выдачу.

SteamID64 — публичный идентификатор всего Steam-профиля человека; отчёт
в discord-режиме доступен гостю по share-токену. Проверка ПОДСТРОКИ на
реальном формате ответа GET — как требует спека.
"""
import json
import uuid

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
```

- [ ] **Step 3: Убедиться, что новые тесты падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_analysis_pipeline.py -q -k external`
Expected: FAIL (`unexpected keyword argument 'steam_id'`)
Run: `.\.venv\Scripts\python.exe -m pytest tests/test_privacy_steam_id.py -q`
Expected: FAIL (нет `update_user_steam_id`? — есть из Task 2; падение будет
на `update_session(..., external_benchmark=...)`, если колонка не подхвачена —
или PASS, если Task 2 уже дал колонку; в этом случае тест фиксирует инвариант)

- [ ] **Step 4: analysis_pipeline.py — параметры и вызов**

Сигнатура `run_pipeline` — после `history_provider`:

```python
                 steam_id: Optional[str] = None,
                 external_fetcher: Optional[Callable] = None) -> PipelineResult:
```

После строки `drill_history = provider(player_id, ctx.clip_id)` (внутри
MEASURING, до `build_report`):

```python
    # Внешний ранк KovaaK's: чужой недокументированный API — сбой любого
    # рода деградирует в «данных нет», сессию не роняет (контракт спеки).
    external_block, external_reason = None, None
    if steam_id:
        fetcher = external_fetcher
        if fetcher is None:
            from backend.services.kovaaks_client import (
                fetch_benchmark_progress)
            fetcher = fetch_benchmark_progress
        try:
            external_block, external_reason = fetcher(steam_id)
        except Exception:                  # noqa: BLE001 — деградация
            logger.exception("внешний ранк KovaaK's не получен")
            external_block, external_reason = None, "api_error"
```

И в вызов `build_report(...)` добавить:

```python
                          external_benchmark=external_block,
                          external_unavailable_reason=external_reason,
```

- [ ] **Step 5: analysis_task.py — передача и персист**

В вызов `pipeline(...)` добавить `steam_id=job.steam_id,`.
В `db.update_session(sid, status="COMPLETED", ...)` добавить:

```python
            external_benchmark=(
                json.dumps(result.evidence_report["external_benchmark"],
                           ensure_ascii=False)
                if "external_benchmark" in result.evidence_report else None),
```

- [ ] **Step 6: Прогнать тесты**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_analysis_pipeline.py tests/test_privacy_steam_id.py tests/test_upload_flow.py tests/test_worker.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```powershell
git add backend/services/analysis_pipeline.py backend/services/analysis_task.py tests/test_analysis_pipeline.py tests/test_privacy_steam_id.py
git commit -m "feat(backend): снапшот KovaaK's через пайплайн — MEASURING до коуча, приватность steam_id тестом"
```

---

### Task 5: Гейт тира в каталоге дриллов

**Files:**
- Modify: `coach/drill_catalog.py` (kovaaks_scenario, TIER_KEYS, гейт, меню)
- Test: `tests/test_drill_catalog.py` (дописать)

**Interfaces:**
- Consumes: формат снапшота (Task 1).
- Produces:
  `menu_drill_ids(training_platform=None, external_benchmark=None) -> frozenset`;
  `menu_for_prompt(training_platform=None, external_benchmark=None) -> str`;
  `tier_threshold(metric: str, tier: int, external_benchmark) -> Optional[float]`;
  `external_scenario_entry(metric: str, tier: int, external_benchmark)
  -> Optional[dict]`; `TIER_KEYS = {1: "novice", 2: "intermediate",
  3: "advanced"}`; `CatalogDrill.kovaaks_scenario: Optional[str]`.
  Обратная совместимость: старые вызовы с одним аргументом работают.

- [ ] **Step 1: Падающие тесты (дописать в tests/test_drill_catalog.py)**

```python
# --- Внешний гейт тира (KovaaK's S5) -----------------------------------------

def _snap(tiers):
    return {"source": "kovaaks_webapp_unofficial", "season": "S5",
            "fetched_at": "x", "tiers_failed": [], "tiers": tiers}


def _tier(scenarios):
    return {"overall_rank": 0, "benchmark_progress": 0, "scenarios": scenarios}


SNAP_PLAYS_T2 = _snap({
    "novice": _tier({"VT ww5t Novice S5": {
        "score": 900, "scenario_rank": 1, "rank_maxes": [990, 1090, 1190, 1290]}}),
    "intermediate": _tier({"VT ww5t Intermediate S5": {
        "score": 1350, "scenario_rank": 1,
        "rank_maxes": [1310, 1400, 1490, 1560]}}),
})

SNAP_T1_MAXED = _snap({
    "novice": _tier({"VT ww5t Novice S5": {
        "score": 1290, "scenario_rank": 4,
        "rank_maxes": [990, 1090, 1190, 1290]}}),
})


def test_no_block_is_todays_behaviour():
    """Регресс-инвариант: без снапшота меню как сегодня."""
    assert menu_drill_ids("kovaaks") == menu_drill_ids("kovaaks", None)
    assert menu_drill_ids(None) == menu_drill_ids(None, None)


def test_any_score_admits_kovaaks_regardless_of_platform():
    ids = menu_drill_ids(None, SNAP_PLAYS_T2)
    assert "consistency_t1_vt_ww5t_novice" in ids   # факт владения > анкета


def test_tier2_opens_when_tier2_scenario_played():
    ids = menu_drill_ids("kovaaks", SNAP_PLAYS_T2)
    assert "consistency_t2_vt_ww5t_intermediate" in ids
    # у bias скоров нет ни на одном тире -> его tier 2 закрыт
    assert "bias_t2_vt_1w3ts_intermediate" not in ids


def test_tier2_opens_when_tier1_hit_max_rank_maxes():
    ids = menu_drill_ids("kovaaks", SNAP_T1_MAXED)
    assert "consistency_t2_vt_ww5t_intermediate" in ids


def test_missing_tier_opens_nothing():
    # intermediate отсутствует в снапшоте -> tier 3 закрыт по обоим правилам
    ids = menu_drill_ids("kovaaks", SNAP_T1_MAXED)
    assert "consistency_t3_vt_ww5t_advanced" not in ids


def test_gate_never_touches_ingame_range():
    ids = menu_drill_ids("kovaaks", SNAP_PLAYS_T2)
    # ingame/range выше tier 1 не открываются внешним сигналом
    assert "consistency_ingame_t2_dm_tempo" not in ids
    assert "bias_ingame_t2_range_strict" not in ids


def test_every_metric_keeps_an_option():
    from engine.metrics.criterion import CORE_METRICS
    for snap in (None, SNAP_PLAYS_T2, SNAP_T1_MAXED):
        for tp in (None, "ingame", "kovaaks"):
            ids = menu_drill_ids(tp, snap)
            for metric in CORE_METRICS:
                assert any(
                    get_catalog_drill(i).metric == metric for i in ids), (
                    f"метрика {metric} осиротела при tp={tp}")


def test_threshold_prefers_snapshot_max_over_catalog():
    # снапшотный max(rank_maxes)=1290 совпадает с каталогом; проверим победу
    # снапшота на изменённых порогах (внутрисезонная правка Voltaic)
    snap = _snap({"novice": _tier({"VT ww5t Novice S5": {
        "score": 1, "scenario_rank": 0, "rank_maxes": [10, 20, 9999]}})})
    assert tier_threshold("consistency", 1, snap) == 9999
    assert tier_threshold("consistency", 1, None) == 1290   # фолбэк: каталог


def test_prompt_menu_quotes_gate_numbers():
    text = menu_for_prompt("kovaaks", SNAP_PLAYS_T2)
    assert "1350" in text        # скор, который ел гейт
    assert "1560" in text        # max(rank_maxes) intermediate
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_drill_catalog.py -q`
Expected: FAIL (нет `tier_threshold`, лишние аргументы)

- [ ] **Step 3: Реализовать в drill_catalog.py**

В `CatalogDrill` после `rank_thresholds`:

```python
    kovaaks_scenario: Optional[str] = None
```

Заполнить у девяти kovaaks-дриллов ИМЕНЕМ ИЗ КАТАЛОЖНОГО `name` (например,
`"VT ww5t Novice S5"` у consistency_t1). ВНИМАНИЕ: точные имена сценариев в
API сверяются в Task 9 по живой фикстуре — здесь стартуем с display-имён.

После `CATALOG` добавить:

```python
TIER_KEYS = {1: "novice", 2: "intermediate", 3: "advanced"}


def _drill_for(metric: str, tier: int) -> Optional[CatalogDrill]:
    return next((d for d in CATALOG[metric]
                 if d.tier == tier and d.platform == "kovaaks"), None)


def external_scenario_entry(metric: str, tier: int,
                            external_benchmark: Optional[dict]
                            ) -> Optional[dict]:
    """Запись сценария (score/rank_maxes) из снапшота для метрики+тира.

    Отсутствующий тир/сценарий -> None: нет тира = нет скоров (спека)."""
    if not external_benchmark:
        return None
    drill = _drill_for(metric, tier)
    if drill is None or drill.kovaaks_scenario is None:
        return None
    tier_block = (external_benchmark.get("tiers") or {}).get(TIER_KEYS[tier])
    if not tier_block:
        return None
    return (tier_block.get("scenarios") or {}).get(drill.kovaaks_scenario)


def tier_threshold(metric: str, tier: int,
                   external_benchmark: Optional[dict]) -> Optional[float]:
    """Верхний порог тира: max(rank_maxes) снапшота (порядок массива в
    неофициальном API не задокументирован — max снимает предположение);
    фолбэк — max(rank_thresholds) каталога. Коуч цитирует ЭТИ ЖЕ числа."""
    entry = external_scenario_entry(metric, tier, external_benchmark)
    maxes = (entry or {}).get("rank_maxes") or []
    numeric = [m for m in maxes if isinstance(m, (int, float))]
    if numeric:
        return float(max(numeric))
    drill = _drill_for(metric, tier)
    if drill is not None and drill.rank_thresholds:
        return float(max(drill.rank_thresholds.values()))
    return None


def _score(entry: Optional[dict]) -> float:
    value = (entry or {}).get("score")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _has_any_score(external_benchmark: Optional[dict]) -> bool:
    if not external_benchmark:
        return False
    return any(
        _score(sc) > 0
        for tier in (external_benchmark.get("tiers") or {}).values()
        for sc in (tier.get("scenarios") or {}).values())


def external_tier_allowed(metric: str, tier: int,
                          external_benchmark: Optional[dict]) -> bool:
    """Правило 2 спеки — ТОЛЬКО для kovaaks-дриллов: тир T открыт, если
    сценарий тира T уже играется (score > 0) ИЛИ сценарий T-1 достиг
    верхнего порога СВОЕГО тира. Пороги — из tier_threshold (единый
    источник с промптом)."""
    if tier == 1:
        return True
    if _score(external_scenario_entry(metric, tier, external_benchmark)) > 0:
        return True
    prev_entry = external_scenario_entry(metric, tier - 1, external_benchmark)
    if prev_entry is None:
        return False                    # отсутствующий тир не открывает
    threshold = tier_threshold(metric, tier - 1, external_benchmark)
    return threshold is not None and _score(prev_entry) >= threshold
```

Переписать `_tier1_drills` → `_menu_drills` (докстринг про None-схлопывание
сохранить дословно):

```python
def _menu_drills(training_platform: Optional[str],
                 external_benchmark: Optional[dict]) -> List[CatalogDrill]:
    """Меню дриллов: ingame/range — всегда tier 1 (перенос в игру меряет
    движок, внешний сигнал их не открывает); kovaaks — по факту владения
    (анкета ИЛИ живые скоры) и внешнему гейту тира.

    None схлопывается в "ingame" СОЗНАТЕЛЬНО (не промптовым дефолтом): Valorant
    есть у каждого, чей клип мы анализируем; KovaaK's — нет. Рекомендация
    тренажёра без владения невыполнима; in-game владельцу KovaaK's — лишь
    неоптимальна. KovaaK's появляется в меню при явном "kovaaks" ИЛИ при
    живых скорах в снапшоте (факт владения сильнее анкеты)."""
    include_kovaaks = (training_platform == "kovaaks"
                       or _has_any_score(external_benchmark))
    menu: List[CatalogDrill] = []
    for metric in CORE_METRICS:
        for d in CATALOG[metric]:
            if d.platform == "kovaaks":
                if include_kovaaks and external_tier_allowed(
                        metric, d.tier, external_benchmark):
                    menu.append(d)
            elif d.tier == 1:
                menu.append(d)
    return menu


def menu_drill_ids(training_platform: Optional[str] = None,
                   external_benchmark: Optional[dict] = None) -> frozenset:
    """Допустимые drill_id; гейтится валидатором механически."""
    return frozenset(cd.drill_id
                     for cd in _menu_drills(training_platform,
                                            external_benchmark))


def menu_for_prompt(training_platform: Optional[str] = None,
                    external_benchmark: Optional[dict] = None) -> str:
    """Меню для промпта; у kovaaks-дриллов — РОВНО числа гейта (скор/порог)."""
    lines = ["Меню дриллов (выбирай drill_id ТОЛЬКО отсюда):"]
    for cd in _menu_drills(training_platform, external_benchmark):
        line = (f"- {cd.drill_id} (метрика {cd.metric}, платформа"
                f" {cd.platform}): {cd.name}")
        entry = external_scenario_entry(cd.metric, cd.tier, external_benchmark)
        if cd.platform == "kovaaks" and entry is not None:
            threshold = tier_threshold(cd.metric, cd.tier, external_benchmark)
            score = _score(entry)
            line += (f" — текущий скор игрока {score:g}, верхний порог тира"
                     f" {threshold:g}" if threshold is not None
                     else f" — текущий скор игрока {score:g}")
        lines.append(line)
    return "\n".join(lines)
```

- [ ] **Step 4: Прогнать тесты каталога и соседей**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_drill_catalog.py tests/test_coach_prompt.py tests/test_coach_validate.py -q`
Expected: PASS (сигнатуры обратно совместимы — старые одноаргументные вызовы
работают)

- [ ] **Step 5: Commit**

```powershell
git add coach/drill_catalog.py tests/test_drill_catalog.py
git commit -m "feat(coach): внешний гейт тира kovaaks-дриллов — max(rank_maxes), анти-сирота, регресс-инвариант"
```

---

### Task 6: Заземление внешних чисел в валидаторе

**Files:**
- Modify: `coach/validate.py` (`_known_numbers`, новый bare-check, вызов menu)
- Test: `tests/test_coach_validate.py` (дописать)

**Interfaces:**
- Consumes: `menu_drill_ids(training_platform, external_benchmark)` (Task 5);
  блок `external_benchmark` в evidence (Task 3).
- Produces: валидатор ловит выдуманные внешние скоры; меню гейтится с учётом
  снапшота. ВАЖНО: коммитится ВМЕСТЕ с Task 7 (промпт открывает числа коучу
  тем же коммитом, что валидатор их заземляет — инвариант спеки).

- [ ] **Step 1: Падающие тесты (дописать в tests/test_coach_validate.py)**

```python
# --- Заземление внешних скоров KovaaK's --------------------------------------
# использовать фабрики отчёта/коуча этого файла (evidence с одним finding
# metric="correction" confidence="diagnosis" и валидным дриллом)

EXTERNAL = {"source": "kovaaks_webapp_unofficial", "season": "S5",
            "fetched_at": "x", "tiers_failed": [],
            "tiers": {"novice": {"overall_rank": 1, "benchmark_progress": 0.2,
                                 "scenarios": {"VT Pasu Novice S5": {
                                     "score": 812, "scenario_rank": 2,
                                     "rank_maxes": [555, 660, 745, 800]}}}}}


def test_external_score_in_text_passes():
    evidence = _evidence()                  # фабрика файла
    evidence["external_benchmark"] = EXTERNAL
    coach = _coach(summary="Твой Pasu — 812 при верхнем пороге 800.")
    assert validate_coach_report(coach, evidence) == []


def test_invented_external_score_is_caught():
    evidence = _evidence()
    evidence["external_benchmark"] = EXTERNAL
    coach = _coach(summary="Твой Pasu — 999, почти топ.")
    errors = validate_coach_report(coach, evidence)
    assert any("999" in e for e in errors)


def test_reports_without_block_skip_bare_number_check():
    """Регресс-инвариант: без блока новые проверки не включаются."""
    evidence = _evidence()                  # блока нет
    coach = _coach(summary="Сыграно 999 матчей (число не из отчёта).")
    # bare-числа без единицы РАНЬШЕ не проверялись — поведение сохранено
    assert validate_coach_report(coach, evidence) == []


def test_menu_gate_respects_external_block():
    evidence = _evidence()
    evidence["clip"]["training_platform"] = None      # анкеты нет
    evidence["external_benchmark"] = EXTERNAL          # но скоры живые
    coach = _coach(drill_id="correction_t1_vt_pasu_novice")
    assert validate_coach_report(coach, evidence) == []
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_validate.py -q -k external`
Expected: FAIL (menu-гейт режет kovaaks-дрилл; 999 не ловится)

- [ ] **Step 3: Реализовать в validate.py**

В `_known_numbers` перед `return pool` добавить:

```python
    # Внешние скоры KovaaK's (S5): числа чужого измерения, которые коуч
    # имеет право цитировать — заземляем тем же множеством, что HU.
    external = evidence.get("external_benchmark") or {}
    for tier in (external.get("tiers") or {}).values():
        for key in ("overall_rank", "benchmark_progress"):
            if _is_number(tier.get(key)):
                pool.append(float(tier[key]))
        for sc in (tier.get("scenarios") or {}).values():
            for key in ("score", "scenario_rank"):
                if _is_number(sc.get(key)):
                    pool.append(float(sc[key]))
            pool.extend(float(m) for m in (sc.get("rank_maxes") or [])
                        if _is_number(m))
```

Новый check после `_check_cm_numbers`:

```python
_BARE_NUMBER_RE = re.compile(r"(?<![\w.,+\-–—:])(\d{3,5})(?![\w.,%])")


def _check_bare_numbers(text: str, pool: List[float], frames: set,
                        where: str) -> List[str]:
    """Голые числа 3-5 цифр (скоры KovaaK's пишутся без единицы) обязаны
    существовать в отчёте. Проверка включается ТОЛЬКО при наличии блока
    external_benchmark — без него поведение прежнее (регресс-инвариант).
    Номера кадров легальны (frames)."""
    errors = []
    for match in _BARE_NUMBER_RE.finditer(text or ""):
        value = float(match.group(1))
        if int(value) in frames:
            continue
        if not any(abs(value - known) <= 0.5 for known in pool):
            errors.append(f"число {match.group(1)} ({where}) не найдено в "
                          f"evidence-JSON — внешние скоры тоже нельзя выдумывать")
    return errors
```

В `validate_coach_report`:
- после `numbers_known = _known_numbers(evidence)` добавить:

```python
    has_external = "external_benchmark" in evidence
    def _bare(text: str, where: str) -> List[str]:
        if not has_external:
            return []
        return _check_bare_numbers(text, numbers_known, frames_known, where)
```

- рядом с каждым парным вызовом `_check_hu_numbers/_check_cm_numbers`
  (explanation, summary, rationale, progress explanation) добавить
  `errors.extend(_bare(<тот же текст>, where))`.
- заменить строку menu:

```python
    menu_ids = menu_drill_ids(
        (evidence.get("clip") or {}).get("training_platform"),
        evidence.get("external_benchmark"))
```

- и текст ошибки меню (теперь тиры бывают выше первого):

```python
            errors.append(
                f"{where} не из допустимого меню (tier {cd.tier} закрыт "
                f"гейтом или платформа не твоя)")
```

- [ ] **Step 4: Прогнать валидатор целиком**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_validate.py -q`
Expected: PASS (включая старые тесты: без блока bare-check выключен, текст
ошибки меню проверить — если старый тест assert'ит «первого клипа», обновить
его строку на новую формулировку)

- [ ] **Step 5: НЕ коммитить — коммит общий с Task 7 (шаг 6 Task 7)**

---

### Task 7: Коуч видит и цитирует внешние скоры

**Files:**
- Modify: `coach/prompt.py` (меню с блоком; правило в SYSTEM_PROMPT)
- Modify: `coach/schema.py` (Drill.external_score / external_threshold)
- Modify: `coach/drill_catalog.py` (`assemble_drill`/`finalize_plan` — external)
- Modify: `backend/services/analysis_pipeline.py:132` (finalize_plan с блоком)
- Test: `tests/test_coach_prompt.py`, `tests/test_drill_catalog.py` (дописать)

**Interfaces:**
- Consumes: `menu_for_prompt(tp, external)`, `external_scenario_entry`,
  `tier_threshold` (Task 5).
- Produces: `Drill.external_score: Optional[float]`,
  `Drill.external_threshold: Optional[float]` (фронт читает в Task 8);
  `finalize_plan(selections, findings, external_benchmark=None)`.

- [ ] **Step 1: Падающие тесты**

В tests/test_coach_prompt.py:

```python
def test_user_text_menu_uses_external_block():
    report = {"clip": {"training_platform": None},
              "external_benchmark": EXTERNAL}     # словарь из Task 6 тестов
    text = build_user_text(report)
    assert "correction_t1_vt_pasu_novice" in text  # kovaaks по факту скоров
    assert "812" in text                            # числа гейта в меню
```

В tests/test_drill_catalog.py:

```python
def test_assemble_drill_carries_external_numbers():
    selection = DrillSelection(priority=1,
                               drill_id="correction_t1_vt_pasu_novice",
                               rationale="r")
    finding = {"metric": "correction", "confidence": "diagnosis", "values": {}}
    plan = finalize_plan([selection], [finding],
                         external_benchmark=EXTERNAL)   # тот же словарь
    drill = plan.drills[0]
    assert drill.external_score == 812
    assert drill.external_threshold == 800


def test_assemble_drill_without_block_leaves_none():
    selection = DrillSelection(priority=1,
                               drill_id="correction_ingame_t1_range_flicks",
                               rationale="r")
    finding = {"metric": "correction", "confidence": "diagnosis", "values": {}}
    drill = finalize_plan([selection], [finding]).drills[0]
    assert drill.external_score is None and drill.external_threshold is None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_prompt.py tests/test_drill_catalog.py -q -k external`
Expected: FAIL

- [ ] **Step 3: schema.py — поля Drill**

В `class Drill` добавить (Optional-контракт: отсутствие данных легально):

```python
    external_score: Optional[float] = None       # скор игрока в KovaaK's
    external_threshold: Optional[float] = None   # верхний порог тира (гейт)
```

- [ ] **Step 4: prompt.py и drill_catalog.py**

prompt.py, `build_user_text`, заменить строку menu:

```python
    parts.append(menu_for_prompt(
        (report.get("clip") or {}).get("training_platform"),
        report.get("external_benchmark")))
```

В SYSTEM_PROMPT добавить правило 10:

```
10. Если в evidence-JSON есть блок external_benchmark (скоры KovaaK's) — \
можешь цитировать скоры и пороги ИЗ НЕГО (и из меню дриллов) дословно; \
любые другие внешние числа запрещены. Блок может отсутствовать или быть \
неполным (tiers_failed) — тогда просто не упоминай внешний ранг.
```

drill_catalog.py:

```python
def assemble_drill(selection: DrillSelection, finding: dict,
                   external_benchmark: Optional[dict] = None) -> Drill:
    """Финальный Drill: имя/платформа/доза/тир из каталога, критерий из values,
    внешний скор/порог — те же числа, что ел гейт (единый источник)."""
    cd = _CATALOG_BY_ID[selection.drill_id]
    criterion = build_criterion(cd.metric, finding.get("values", {}))
    entry = (external_scenario_entry(cd.metric, cd.tier, external_benchmark)
             if cd.platform == "kovaaks" else None)
    return Drill(
        priority=selection.priority,
        drill_id=cd.drill_id,
        name=cd.name,
        platform=cd.platform,
        tier=cd.tier,
        dose=cd.dose,
        target_metric=cd.metric,
        rationale=selection.rationale,
        success_criterion=criterion.text,
        criterion=criterion,
        external_score=_score(entry) if entry is not None else None,
        external_threshold=(tier_threshold(cd.metric, cd.tier,
                                           external_benchmark)
                            if entry is not None else None),
    )
```

`finalize_plan(selections, findings, external_benchmark=None)` — пробросить
третий аргумент в `assemble_drill(sel, by_metric[cd.metric],
external_benchmark)`.

analysis_pipeline.py `_run_coach` (строка 132) — finalize_plan получает блок:

```python
    plan = finalize_plan(result.coach_report.drills,
                         report.get("findings", []),
                         report.get("external_benchmark"))
```

- [ ] **Step 5: Прогнать коуч-тесты**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_prompt.py tests/test_drill_catalog.py tests/test_coach_schema.py tests/test_coach_validate.py tests/test_analysis_pipeline.py -q`
Expected: PASS

- [ ] **Step 6: Commit (ОБЩИЙ с Task 6 — заземление тем же коммитом)**

```powershell
git add coach/validate.py coach/prompt.py coach/schema.py coach/drill_catalog.py backend/services/analysis_pipeline.py tests/test_coach_validate.py tests/test_coach_prompt.py tests/test_drill_catalog.py
git commit -m "feat(coach): внешние скоры KovaaK's в промпте и плане + заземление в валидаторе тем же коммитом"
```

---

### Task 8: Фронт — поле SteamID64 и строка внешнего ранга

**Files:**
- Modify: `frontend/src/api.js` (metaForm: steam_id)
- Modify: `frontend/src/components/UploadForm.js` (поле + предзаполнение)
- Modify: `frontend/src/App.js` (прокинуть auth.user в UploadForm)
- Modify: `frontend/src/components/report/DrillTable.js` (скор/порог дрилла)
- Modify: `frontend/src/components/report/ReportView.js` (строка ранга в ClipMeta)
- Test: `frontend/src/components/UploadForm.test.js` (создать),
  дописать в `frontend/src/components/report/` тест DrillTable при
  необходимости создать `DrillTable.test.js`

**Interfaces:**
- Consumes: `/me.user.steam_id` (Task 2); `drill.external_score /
  external_threshold` в coach_report (Task 7); блок
  `evidence_report.external_benchmark` (Task 3).
- Produces: FormData c `steam_id`; UI-строки.

- [ ] **Step 1: Падающие RTL-тесты (frontend/src/components/UploadForm.test.js)**

```jsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import UploadForm from './UploadForm';

test('поле SteamID64 присутствует и уходит в onSubmit', async () => {
  const onSubmit = jest.fn();
  render(<UploadForm onSubmit={onSubmit} submitting={false} user={null} />);
  await userEvent.click(screen.getByText(/сенса и матч/i)); // раскрыть extras
  const field = screen.getByLabelText(/steamid64/i);
  await userEvent.type(field, '76561198000000001');
  // сабмит без файла заблокирован — проверяем только значение поля
  expect(field).toHaveValue('76561198000000001');
});

test('steam_id предзаполняется из аккаунта', async () => {
  render(<UploadForm onSubmit={() => {}} submitting={false}
                     user={{ steam_id: '76561198000000009' }} />);
  await userEvent.click(screen.getByText(/сенса и матч/i));
  expect(screen.getByLabelText(/steamid64/i))
    .toHaveValue('76561198000000009');
});
```

И тест DrillTable (`frontend/src/components/report/DrillTable.test.js`):

```jsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import DrillTable from './DrillTable';

const DRILL = {
  priority: 1, drill_id: 'correction_t1_vt_pasu_novice',
  name: 'VT Pasu Novice S5', platform: 'kovaaks', tier: 1,
  dose: '3 подхода по 5 минут', target_metric: 'correction',
  rationale: 'r', success_criterion: 'критерий',
  external_score: 812, external_threshold: 800,
};

test('дрилл со скором KovaaK\'s показывает скор и порог', () => {
  render(<DrillTable drills={[DRILL]} />);
  expect(screen.getByText(/812/)).toBeInTheDocument();
  expect(screen.getByText(/800/)).toBeInTheDocument();
});

test('без внешних чисел строка скора не рендерится', () => {
  render(<DrillTable drills={[{ ...DRILL, external_score: null,
                                external_threshold: null }]} />);
  expect(screen.queryByText(/скор/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd frontend; $env:CI="true"; npx react-scripts test --watchAll=false`
Expected: FAIL (нет поля/строки)

- [ ] **Step 3: Реализовать**

api.js `metaForm` — добавить в деструктуризацию `steamId` и:

```js
  if (steamId) form.append('steam_id', steamId);
```

UploadForm.js — принять проп `user`, состояние:

```jsx
  const [steamId, setSteamId] = useState('');
  // предзаполнение из аккаунта, когда /me долетел ПОСЛЕ монтирования формы
  React.useEffect(() => {
    if (user?.steam_id && !steamId) setSteamId(user.steam_id);
  }, [user]);           // eslint-disable-line react-hooks/exhaustive-deps
```

В `onSubmit({...})` добавить `steamId: steamId.trim()`. В `extras-grid`
добавить поле (после «Тренировки»):

```jsx
          <div className="field">
            <label htmlFor="steam-id">SteamID64 (ранг KovaaK&apos;s)</label>
            <input id="steam-id" type="text" inputMode="numeric"
              pattern="\d{17}" value={steamId}
              onChange={(e) => setSteamId(e.target.value)}
              placeholder="76561198…" />
            <span className="field-hint">
              17 цифр — найти на steamid.io или в URL профиля Steam.
              Подтянем ваш ранг Voltaic S5 из KovaaK&apos;s.
            </span>
          </div>
```

App.js — `<UploadForm onSubmit={handleSubmit} submitting={submitting}
user={auth.user} />`.

ReportView.js `ClipMeta` — принять третий проп `external` и добавить строку
(вызов: `<ClipMeta clip={engine.clip} profile={engine.profile}
external={engine.external_benchmark} />`):

```jsx
      {external && (
        <div>
          <dt>Ранг KovaaK&apos;s</dt>
          <dd>Voltaic {external.season}
            {Object.keys(external.tiers ?? {}).length > 0 &&
              ` · тиров с данными: ${Object.keys(external.tiers).length}`}
          </dd>
        </div>
      )}
```

DrillTable.js — в рендер строки дрилла добавить (стилистика файла):

```jsx
        {drill.external_score != null && (
          <div className="drill-external">
            скор в KovaaK&apos;s: {drill.external_score}
            {drill.external_threshold != null &&
              ` · верхний порог тира: ${drill.external_threshold}`}
          </div>
        )}
```

(точное место — рядом с success_criterion; посмотреть текущую разметку
DrillTable и вставить в ячейку критерия/названия, класс `.drill-external`
добавить в index.css: `font-family: var(--font-mono); font-size: 12px;
color: var(--dim);`).

- [ ] **Step 4: Прогнать фронт-тесты и сборку**

Run: `cd frontend; $env:CI="true"; npx react-scripts test --watchAll=false`
Expected: PASS
Run: `cd frontend; npm run build`
Expected: build без ошибок

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/api.js frontend/src/components/UploadForm.js frontend/src/components/UploadForm.test.js frontend/src/App.js frontend/src/components/report/ReportView.js frontend/src/components/report/DrillTable.js frontend/src/components/report/DrillTable.test.js frontend/src/index.css
git commit -m "feat(frontend): поле SteamID64 с предзаполнением + внешний ранг и скоры дриллов в отчёте"
```

---

### Task 9: Сезонные константы, фикстура соответствия, живой прогон

**Files:**
- Create: `tests/fixtures/kovaaks_s5_snapshot.json` (записать с живого API)
- Create: `tests/test_kovaaks_season_alignment.py`
- Modify: `coach/drill_catalog.py` (поправить `kovaaks_scenario`, если живые
  имена отличаются от display-имён)
- Modify: `CLAUDE.md` (краткий абзац об интеграции)
- Modify: `.env` (пользовательский, вне git — руками)

**Interfaces:**
- Consumes: всё выше.
- Produces: фикстурный тест «каталог ↔ API не разъехались»; рабочие
  benchmarkId в .env.

Это ЕДИНСТВЕННАЯ задача с ручными шагами (нужна сеть и реальный SteamID) —
исполнитель останавливается и просит пользователя, если сети нет.

- [ ] **Step 1: Найти benchmarkId трёх тиров S5**

Открыть kovaaks.com/kovaaks/benchmark-tracker (или app.voltaic.gg), выбрать
Voltaic S5 Novice/Intermediate/Advanced, в DevTools → Network найти запросы
`player-progress-rank-benchmark?benchmarkId=NNN`. Записать три ID в `.env`:
`KOVAAKS_S5_BENCHMARK_IDS=novice=?,intermediate=?,advanced=?`

- [ ] **Step 2: Записать фикстуру живого ответа**

```powershell
.\.venv\Scripts\python.exe -c "import json, os; from backend.services import kovaaks_client as kc; snap, reason = kc.fetch_benchmark_progress(os.environ['TEST_STEAM_ID']); print(json.dumps(snap or {'reason': reason}, ensure_ascii=False, indent=2))" > tests/fixtures/kovaaks_s5_snapshot.json
```

(`TEST_STEAM_ID` — SteamID автора с сыгранными S5-сценариями; попросить у
пользователя. Если скоров нет — годится и снапшот с score=0, важен ПЕРЕЧЕНЬ
имён сценариев: для фикстуры имён допустимо временно ослабить no_scores-ветку
локальным скриптом, НЕ кодом.)

- [ ] **Step 3: Тест соответствия каталога фикстуре**

```python
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
```

- [ ] **Step 4: Выровнять kovaaks_scenario по фикстуре**

Прогнать тест; если имена из API отличаются от display-имён каталога —
поправить `kovaaks_scenario` у соответствующих дриллов (drill_id НЕ трогать).

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_kovaaks_season_alignment.py -q`
Expected: PASS

- [ ] **Step 5: Живой прогон**

Запустить backend + frontend, загрузить клип с заполненным SteamID64,
убедиться: (а) отчёт COMPLETED, (б) в evidence-JSON есть external_benchmark,
(в) в отчёте видна строка «Ранг KovaaK's», (г) при выключенном интернете /
битом steam_id разбор всё равно COMPLETED без блока. Пункт (г) обязателен —
это главный контракт спеки.

- [ ] **Step 6: CLAUDE.md**

В раздел «Coach (Phase B)» после coach/validate.py добавить:

```
- `backend/services/kovaaks_client.py` — внешний ранк Voltaic S5 из
  неофициального API kovaaks.com по SteamID64 (KOVAAKS_S5_BENCHMARK_IDS);
  мягкая деградация: сбой -> отчёт без блока external_benchmark, не FAILED.
  Гейт тира kovaaks-дриллов и цитаты коуча едят ОДНИ числа (max(rank_maxes)
  снапшота, фолбэк — rank_thresholds каталога). steam_id в отчёт не пишется.
```

- [ ] **Step 7: Полный прогон и коммит**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 413+новые passed (11 dataset1-падений — до-веточные)
Run: `cd frontend; $env:CI="true"; npx react-scripts test --watchAll=false`
Expected: PASS

```powershell
git add tests/fixtures/kovaaks_s5_snapshot.json tests/test_kovaaks_season_alignment.py coach/drill_catalog.py CLAUDE.md
git commit -m "chore(coach): сезонная фикстура KovaaK's S5 — сверка имён сценариев каталога с живым API"
```

---

## Self-Review (выполнено при написании)

1. **Покрытие спеки:** клиент+бюджет+кэш+reasons — Task 1; SteamID
   валидация/хранение — Task 2; снапшот в evidence/колонку + SCHEMA_VERSION
   тем же коммитом — Task 3/4; приватность подстрокой — Task 4; гейт (оба
   правила, только kovaaks, анти-сирота, max(rank_maxes), фолбэк) — Task 5;
   заземление+меню в валидаторе — Task 6 (коммит общий с Task 7); промпт и
   числа гейта — Task 7; фронт — Task 8; сезонная сверка и живой прогон —
   Task 9. Граница с 2C — кодом не выражается (2C не реализуется), правило
   зафиксировано в докстринге `_menu_drills` («меню — допуск, не
   рекомендация» — исполнителю Task 5 включить эту фразу в докстринг).
2. **Плейсхолдеры:** benchmarkId и точные имена сценариев физически
   неизвестны до живого прогона — это не TBD, а ручной шаг Task 9 с
   фикстурным тестом, как требует спека.
3. **Типы согласованы:** снапшот-словарь один во всех задачах; сигнатуры
   `menu_drill_ids(tp, external)`, `tier_threshold(metric, tier, external)`,
   `finalize_plan(selections, findings, external_benchmark)` используются
   единообразно в Tasks 5–7.
