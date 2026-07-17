# -*- coding: utf-8 -*-
"""Тесты groundedness-валидатора (Stage B2).

Три класса подсаженных ошибок из спеки: фиктивный кадр, выдуманное HU-число,
диагноз-из-гипотезы. Плюс тесты на фикстурах: репрезентативные синтетические
schema-корректные CoachReport/evidence-JSON проходят чисто (это не
захваченные реальные ответы VLM, а вручную составленные примеры).
"""
import json
import logging
from pathlib import Path
from typing import List, Optional

import pytest

from coach.schema import CoachReport, DrillSelection, FindingExplained
from coach.validate import run_coach_validated, validate_coach_report

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------- фикстуры

def _evidence() -> dict:
    """Минимальный синтетический evidence-JSON: диагноз + гипотеза."""
    return {
        "schema_version": "1.1",
        "clip": {"player_id": "p", "clip_id": "c", "fps": 60.0},
        "episodes": [
            {
                "index": 1,
                "start_frame": 100,
                "end_frame": 130,
                "multi_from_frame": None,
                "kind": "flick",
                "duel_frames": 20,
                "peak_closing_speed_hu_s": 50.0,
                "birth": {"dx_hu": -3.538, "dy_hu": -1.461, "radial_hu": 3.828},
            }
        ],
        "findings": [
            {
                "metric": "consistency",
                "statement": "разброс низкий, ошибка высокая",
                "values": {"duel_frames": 20, "mae_hu": 1.349, "std_hu": 0.764},
                "confidence": "diagnosis",
                "evidence": [
                    {
                        "frame_start": 105,
                        "frame_end": 130,
                        "episode": 1,
                        "note": "дуэльное окно (20 кадров, radial<=3 HU)",
                        "dx_hu": -2.613,
                        "dy_hu": -0.963,
                        "head_height_px": 63.02,
                    }
                ],
            },
            {
                "metric": "placement",
                "statement": "прицел ниже линии головы",
                "values": {"total": 1, "below": 1, "mean_dy_hu": -1.461},
                "confidence": "hypothesis",
                "evidence": [
                    {
                        "frame": 100,
                        "episode": 1,
                        "note": "появление врага слева: прицел ниже (dy -1.46 HU)",
                        "dx_hu": -3.538,
                        "dy_hu": -1.461,
                        "head_height_px": 54.72,
                    }
                ],
            },
        ],
        "profile": {"player_id": "p", "clips": 1, "duel_mae_hu": 1.349},
    }


def _coach(
    metric: str = "consistency",
    explanation: str = "Ошибка MAE 1.349 HU при разбросе std 0.764 HU.",
    frames: Optional[List[int]] = None,
    confidence: str = "diagnosis",
    drill_id: str = "consistency_t1_vt_ww5t_novice",
    rationale: str = "Разброс низкий, ошибка высокая — нужна повторяемость.",
) -> CoachReport:
    return CoachReport(
        summary="Портрет игрока.",
        findings_explained=[
            FindingExplained(
                metric=metric,
                explanation=explanation,
                evidence_frames=frames if frames is not None else [105],
                confidence=confidence,
            )
        ],
        drills=[DrillSelection(priority=1, drill_id=drill_id, rationale=rationale)],
        caveats=[],
    )


# ------------------------------------------------------- базовая валидность

def test_clean_report_passes():
    assert validate_coach_report(_coach(), _evidence()) == []


def test_valid_fixture_friend_passes_clean():
    coach = CoachReport(**json.loads(
        (FIXTURES / "coach_friend_clip3.json").read_text(encoding="utf-8")))
    evidence = json.loads(
        (FIXTURES / "friend_clip3.json").read_text(encoding="utf-8"))
    assert validate_coach_report(coach, evidence) == []


def test_valid_fixture_author_passes_clean():
    coach = CoachReport(**json.loads(
        (FIXTURES / "coach_author_output_clip.json").read_text(encoding="utf-8")))
    evidence = json.loads(
        (FIXTURES / "author_output_clip.json").read_text(encoding="utf-8"))
    assert validate_coach_report(coach, evidence) == []


# ------------------------------------------------- класс 1: фиктивный кадр

def test_fabricated_frame_caught():
    errors = validate_coach_report(_coach(frames=[105, 999]), _evidence())
    assert len(errors) == 1
    assert "999" in errors[0]


def test_episode_and_window_frames_are_known():
    # границы эпизода (100, 130) и окна (105, 130) — легитимные ссылки
    errors = validate_coach_report(_coach(frames=[100, 105, 130]), _evidence())
    assert errors == []


# --------------------------------------------- класс 2: выдуманное HU-число

def test_fabricated_hu_number_caught():
    errors = validate_coach_report(
        _coach(explanation="Смещение достигает 7.77 HU."), _evidence()
    )
    assert len(errors) == 1
    assert "7.77" in errors[0]


def test_fabricated_hu_number_in_summary_caught():
    coach = _coach().model_copy(update={"summary": "Промах на 9.99 HU."})
    errors = validate_coach_report(coach, _evidence())
    assert any("9.99" in e for e in errors)


def test_rounded_hu_number_passes():
    # -2.613 в JSON, коуч округлил до -2.61; знак может быть опущен в тексте
    errors = validate_coach_report(
        _coach(explanation="В окне смещение dx -2.61 HU (по модулю 2.61 HU)."),
        _evidence(),
    )
    assert errors == []


def test_hu_number_from_note_text_passes():
    # "radial<=3 HU" существует только внутри note-строки улики
    errors = validate_coach_report(
        _coach(explanation="Дуэльное окно определено порогом 3 HU."),
        _evidence(),
    )
    assert errors == []


# ------------------------------------------- класс 3: диагноз-из-гипотезы

def test_confidence_upgrade_caught():
    errors = validate_coach_report(
        _coach(metric="placement", explanation="Прицел ниже: dy -1.46 HU.",
               frames=[100], confidence="diagnosis"),
        _evidence(),
    )
    assert len(errors) == 1
    assert "placement" in errors[0]


def test_hypothesis_with_assertive_stopword_caught():
    errors = validate_coach_report(
        _coach(metric="placement",
               explanation="Однозначно доказано: прицел ниже (dy -1.46 HU).",
               frames=[100], confidence="hypothesis"),
        _evidence(),
    )
    assert len(errors) >= 1
    assert any("placement" in e for e in errors)


def test_diagnosis_explanation_allows_assertive_language():
    errors = validate_coach_report(
        _coach(explanation="Однозначно проблема калибровки: MAE 1.349 HU."),
        _evidence(),
    )
    assert errors == []


def test_stopword_matched_on_word_boundary():
    # «недостаточно» содержит «точно» как подстроку — ложных срабатываний нет
    errors = validate_coach_report(
        _coach(metric="placement",
               explanation="Данных недостаточно, предварительно dy -1.46 HU.",
               frames=[100], confidence="hypothesis"),
        _evidence(),
    )
    assert errors == []


# ------------------------------------------------ незнакомые metric-ссылки

def test_unknown_finding_metric_caught():
    errors = validate_coach_report(
        _coach(metric="reaction_time", explanation="Реакция.", frames=[100]),
        _evidence(),
    )
    assert any("reaction_time" in e for e in errors)


# ---------------------------------------- класс 4: drill_id ↔ каталог ↔ finding

def test_unknown_drill_id_caught():
    errors = validate_coach_report(_coach(drill_id="totally_made_up"), _evidence())
    assert len(errors) == 1
    assert "totally_made_up" in errors[0]


def test_drill_metric_without_finding_caught():
    # bias-дрилл валиден по id, но finding bias в _evidence() нет
    errors = validate_coach_report(
        _coach(drill_id="bias_t1_vt_1w4ts_novice"), _evidence())
    assert len(errors) == 1
    assert "bias" in errors[0]


def test_off_menu_tier_drill_caught():
    # tier-3 id валиден по каталогу и метрика consistency есть среди findings,
    # но первый клип — только tier-1: механический гейт, а не доверие промпту
    errors = validate_coach_report(
        _coach(drill_id="consistency_t3_vt_ww5t_advanced"), _evidence())
    assert len(errors) == 1
    assert "tier" in errors[0].lower()


def test_drill_rationale_hu_number_grounded_ok():
    errors = validate_coach_report(
        _coach(rationale="Ошибка держится около 1.349 HU."), _evidence())
    assert errors == []


def test_drill_rationale_fabricated_hu_caught():
    errors = validate_coach_report(
        _coach(rationale="Промах доходит до 8.88 HU."), _evidence())
    assert any("8.88" in e for e in errors)


# ------------------------------------------------- ретрай и деградация

class RetryStub:
    """Клиент: отдаёт отчёты по очереди, записывает feedback ретрая."""

    def __init__(self, reports: List[CoachReport]):
        self._reports = list(reports)
        self.calls: List[Optional[str]] = []

    def generate(self, report, frame_paths, feedback=None):
        self.calls.append(feedback)
        return self._reports.pop(0)


def test_valid_first_try_no_retry():
    stub = RetryStub([_coach()])
    result = run_coach_validated(stub, _evidence(), [])
    assert result.coach_failed is False
    assert result.coach_report is not None
    assert result.attempts == 1
    assert stub.calls == [None]


def test_retry_passes_errors_as_feedback():
    bad = _coach(frames=[105, 999])
    stub = RetryStub([bad, _coach()])
    result = run_coach_validated(stub, _evidence(), [])
    assert result.coach_failed is False
    assert result.attempts == 2
    assert stub.calls[0] is None
    assert stub.calls[1] is not None and "999" in stub.calls[1]


def test_double_failure_degrades_to_coach_failed(caplog):
    bad = _coach(frames=[105, 999])
    stub = RetryStub([bad, bad])
    with caplog.at_level(logging.ERROR):
        result = run_coach_validated(stub, _evidence(), [])
    assert result.coach_failed is True
    assert result.coach_report is None
    assert result.attempts == 2
    assert any("999" in e for e in result.errors)
    assert any("999" in r.message for r in caplog.records)  # ошибку не глотаем


# --------------------------------------------- progress_explained (Фаза 2B)

def _evidence_with_progress(direction="improved", confidence="hypothesis"):
    return {
        "episodes": [], "findings": [
            {"metric": "consistency", "values": {"mae_hu": 4.8},
             "confidence": "diagnosis", "statement": "", "evidence": []}],
        "drill_progress": [{
            "metric": "consistency", "drill_id": "consistency_t1_vt_ww5t_novice",
            "value_key": "mae_hu", "comparator": "<", "anchor_value": 5.0,
            "anchor_clip_id": "c1", "current_value": 4.8, "delta": -0.2,
            "direction": direction, "confidence": confidence, "series_len": 2,
            "resolved_now": False, "order_uncertain": True}],
    }


def _coach_with_progress(direction="improved", confidence="hypothesis",
                         explanation="точность движется в нужную сторону"):
    from coach.schema import CoachReport, ProgressExplained
    return CoachReport(
        summary="Портрет без чисел.", findings_explained=[], drills=[], caveats=[],
        progress_explained=[ProgressExplained(
            metric="consistency", direction=direction, confidence=confidence,
            explanation=explanation)])


def test_valid_progress_passes():
    from coach.validate import validate_coach_report
    assert validate_coach_report(_coach_with_progress(),
                                 _evidence_with_progress()) == []


def test_grounded_delta_number_passes():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(explanation="ошибка снизилась на 0.2 HU")
    assert validate_coach_report(coach, _evidence_with_progress()) == []


def test_invented_delta_number_rejected():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(explanation="ошибка снизилась на 9.9 HU")
    errors = validate_coach_report(coach, _evidence_with_progress())
    assert any("9.9" in e for e in errors)


def test_direction_mismatch_rejected():
    from coach.validate import validate_coach_report
    # движок сказал improved, коуч заявил regressed
    coach = _coach_with_progress(direction="regressed")
    errors = validate_coach_report(coach, _evidence_with_progress("improved"))
    assert any("направлени" in e for e in errors)


def test_progress_confidence_matched_against_drill_progress():
    from coach.validate import validate_coach_report
    # drill_progress.confidence = hypothesis, коуч заявил diagnosis
    coach = _coach_with_progress(confidence="diagnosis")
    errors = validate_coach_report(coach, _evidence_with_progress(confidence="hypothesis"))
    assert any("confidence" in e for e in errors)


def test_progress_metric_absent_from_drill_progress_rejected():
    from coach.validate import validate_coach_report
    ev = _evidence_with_progress()
    ev["drill_progress"] = []                 # движок ничего не репортил
    errors = validate_coach_report(_coach_with_progress(), ev)
    assert any("drill_progress" in e for e in errors)


def test_causal_attribution_rejected_in_progress():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(explanation="точность выросла благодаря дриллу")
    errors = validate_coach_report(coach, _evidence_with_progress())
    assert any("каузальн" in e.lower() or "благодаря" in e for e in errors)


def test_causal_attribution_rejected_in_summary():
    from coach.schema import CoachReport
    from coach.validate import validate_coach_report
    coach = CoachReport(summary="дрилл сработал и всё стало лучше",
                        findings_explained=[], drills=[], caveats=[])
    errors = validate_coach_report(coach, {"episodes": [], "findings": []})
    assert any("каузальн" in e.lower() or "сработал" in e for e in errors)


def test_causal_attribution_rejected_in_caveats():
    from coach.schema import CoachReport
    from coach.validate import validate_coach_report
    coach = CoachReport(summary="ок", findings_explained=[], drills=[],
                        caveats=["прогресс есть благодаря тренировке"])
    errors = validate_coach_report(coach, {"episodes": [], "findings": []})
    assert errors, "каузальность в caveats должна ловиться"


def test_hedged_progress_forbids_assertive_word():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(confidence="hypothesis",
                                 explanation="точность однозначно движется вниз")
    errors = validate_coach_report(coach, _evidence_with_progress(confidence="hypothesis"))
    assert any("однозначно" in e for e in errors)
