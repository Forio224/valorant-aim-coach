# -*- coding: utf-8 -*-
"""Пайплайн и CLI создают клиента через фабрику провайдеров."""
import coach_cli
from backend.services import analysis_pipeline


def test_pipeline_fallback_uses_factory(monkeypatch):
    calls = {}

    def fake_factory(*args, **kwargs):
        calls["made"] = True
        return object()

    monkeypatch.setattr(
        "coach.providers.factory.create_coach_client", fake_factory)
    # run_coach_validated импортируется ЛОКАЛЬНО внутри _run_coach из
    # coach.validate — патчим по месту определения, не по имени в пайплайне.
    monkeypatch.setattr(
        "coach.validate.run_coach_validated",
        lambda *a, **k: type("R", (), {
            "coach_report": None, "errors": [], "attempts": 1,
            "coach_failed": True})())

    # coach_client=None -> должен пойти в фабрику
    analysis_pipeline._run_coach(
        None, {"findings": []}, [], analysis_pipeline.PipelineConfig())
    assert calls.get("made") is True


def test_coach_cli_accepts_provider_flag(monkeypatch, tmp_path):
    captured = {}

    def fake_factory(provider=None, model=None):
        captured["provider"] = provider
        captured["model"] = model

        class FakeClient:
            def generate(self, *a, **k):
                from coach.schema import CoachReport
                return CoachReport(
                    summary="ок", findings_explained=[], drills=[], caveats=[])

        return FakeClient()

    monkeypatch.setattr(
        "coach.providers.factory.create_coach_client", fake_factory)

    report = tmp_path / "r.json"
    report.write_text('{"findings": []}', encoding="utf-8")
    out = tmp_path / "out.json"

    coach_cli.main(
        ["--provider", "gemini", "--model", "gemini-3.5-flash",
         str(report), "--out", str(out)])
    assert captured["provider"] == "gemini"
    assert captured["model"] == "gemini-3.5-flash"
