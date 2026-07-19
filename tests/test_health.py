# -*- coding: utf-8 -*-
"""Этап 1 запуска: /healthz для оркестратора и аптайм-мониторинга."""
import pytest
from fastapi.testclient import TestClient

from backend.database import DatabaseManager


@pytest.fixture
def api(tmp_path, monkeypatch):
    import backend.main as main

    db = DatabaseManager(f"sqlite:///{tmp_path / 'h.db'}")
    monkeypatch.setattr(main, "db", db)
    return TestClient(main.app), db


def test_healthz_ok(api):
    client, db = api
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "queue" in body and "storage" in body


def test_healthz_reports_db_failure_as_503(api, monkeypatch):
    client, db = api

    class BrokenEngine:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(db, "engine", BrokenEngine())
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["db"] == "error"
