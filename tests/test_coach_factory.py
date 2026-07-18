# -*- coding: utf-8 -*-
"""Тесты фабрики провайдеров: выбор по env/аргументу, дефолт, ошибки."""
import pytest

from coach.providers.anthropic import CoachClient
from coach.providers.factory import DEFAULT_PROVIDER, create_coach_client
from coach.providers.gemini import GeminiCoachClient


@pytest.fixture(autouse=True)
def _dummy_keys(monkeypatch):
    # заглушечные ключи, чтобы конструкторы SDK не падали (сеть не трогается)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.delenv("COACH_PROVIDER", raising=False)
    monkeypatch.delenv("COACH_MODEL", raising=False)


def test_default_provider_is_gemini():
    assert DEFAULT_PROVIDER == "gemini"
    assert isinstance(create_coach_client(), GeminiCoachClient)


def test_env_selects_anthropic(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "anthropic")
    assert isinstance(create_coach_client(), CoachClient)


def test_env_selects_gemini(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "gemini")
    assert isinstance(create_coach_client(), GeminiCoachClient)


def test_explicit_arg_beats_env(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "gemini")
    assert isinstance(create_coach_client(provider="anthropic"), CoachClient)


def test_provider_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "Anthropic")
    assert isinstance(create_coach_client(), CoachClient)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="openai"):
        create_coach_client(provider="openai")


def test_model_passed_through():
    c = create_coach_client(provider="gemini", model="gemini-3.5-flash")
    assert c.model == "gemini-3.5-flash"
