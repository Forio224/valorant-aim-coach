# -*- coding: utf-8 -*-
"""Тесты Pydantic-контракта CoachReport (Stage B1)."""
import pytest
from pydantic import ValidationError

from coach.schema import CoachReport, Drill, FindingExplained


def _valid_report_dict() -> dict:
    return {
        "summary": "Игрок стабилен, но стабильно мимо: проблема калибровки.",
        "findings_explained": [
            {
                "metric": "consistency",
                "explanation": "Разброс низкий (std 0.764 HU), ошибка высокая (MAE 1.349 HU).",
                "evidence_frames": [179, 269],
                "confidence": "diagnosis",
            }
        ],
        "drills": [
            {
                "priority": 1,
                "name": "Tile Frenzy 180",
                "platform": "kovaaks",
                "dose": "3 подхода по 5 минут в день",
                "target_metric": "consistency",
                "success_criterion": "MAE в дуэли < 1.0 HU на следующем клипе",
            }
        ],
        "caveats": ["Pre-aim вердикт — гипотеза: всего 5 эпизодов."],
    }


def test_valid_report_parses():
    report = CoachReport.model_validate(_valid_report_dict())
    assert report.findings_explained[0].metric == "consistency"
    assert report.drills[0].platform == "kovaaks"
    assert report.drills[0].priority == 1


def test_invalid_platform_rejected():
    data = _valid_report_dict()
    data["drills"][0]["platform"] = "aimlab"
    with pytest.raises(ValidationError):
        CoachReport.model_validate(data)


def test_invalid_confidence_rejected():
    data = _valid_report_dict()
    data["findings_explained"][0]["confidence"] = "certain"
    with pytest.raises(ValidationError):
        CoachReport.model_validate(data)


def test_json_roundtrip():
    report = CoachReport.model_validate(_valid_report_dict())
    again = CoachReport.model_validate_json(report.model_dump_json())
    assert again == report


def test_schema_exportable_for_structured_output():
    schema = CoachReport.model_json_schema()
    assert schema["type"] == "object"
    assert "summary" in schema["properties"]
