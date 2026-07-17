# -*- coding: utf-8 -*-
"""Тесты Pydantic-контракта CoachReport (Stage B1)."""
import pytest
from pydantic import ValidationError

from coach.schema import (CoachReport, Drill, DrillSelection,
                          FindingExplained, SuccessCriterion)


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
                "drill_id": "consistency_t1_vt_ww5t_novice",
                "rationale": "Разброс низкий, ошибка высокая — нужна повторяемость.",
            }
        ],
        "caveats": ["Pre-aim вердикт — гипотеза: всего 5 эпизодов."],
    }


def test_valid_report_parses():
    report = CoachReport.model_validate(_valid_report_dict())
    assert report.findings_explained[0].metric == "consistency"
    assert report.drills[0].drill_id == "consistency_t1_vt_ww5t_novice"
    assert report.drills[0].priority == 1


def test_drill_selection_requires_drill_id():
    with pytest.raises(ValidationError):
        DrillSelection.model_validate({"priority": 1, "rationale": "x"})


def test_final_drill_carries_structured_criterion():
    drill = Drill(
        priority=1,
        drill_id="consistency_t1_vt_ww5t_novice",
        name="VT ww5t Novice S5",
        platform="kovaaks",
        tier=1,
        dose="3 подхода по 5 минут",
        target_metric="consistency",
        rationale="повторяемость",
        success_criterion="Средняя ошибка в дуэли < 1.147 HU на следующем клипе.",
        criterion=SuccessCriterion(
            metric="consistency", value_key="mae_hu", comparator="<",
            target=1.147, baseline=1.349,
            text="Средняя ошибка в дуэли < 1.147 HU на следующем клипе.",
        ),
    )
    assert drill.criterion.baseline == 1.349
    assert drill.tier == 1


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


def test_progress_explained_field_defaults_empty():
    from coach.schema import CoachReport, ProgressExplained
    r = CoachReport(summary="s", findings_explained=[], drills=[], caveats=[])
    assert r.progress_explained == []
    pe = ProgressExplained(metric="consistency", direction="improved",
                           confidence="hypothesis", explanation="движется в нужную сторону")
    r2 = CoachReport(summary="s", findings_explained=[], drills=[], caveats=[],
                     progress_explained=[pe])
    assert r2.progress_explained[0].direction == "improved"


def test_progress_direction_is_constrained_enum():
    with pytest.raises(ValidationError):
        from coach.schema import ProgressExplained
        ProgressExplained(metric="bias", direction="insufficient",   # не в enum
                          confidence="hypothesis", explanation="x")
