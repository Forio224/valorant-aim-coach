# -*- coding: utf-8 -*-
"""Тесты детерминированного каталога дриллов Voltaic S5 (Фаза 1)."""
from coach.drill_catalog import (CATALOG, FinalizedPlan, assemble_drill,
                                 build_criterion, finalize_plan,
                                 get_catalog_drill, menu_for_prompt)
from coach.schema import DrillSelection

CORE_METRICS = {"placement", "consistency", "bias", "correction"}


def _finding(metric, values, confidence="diagnosis"):
    return {"metric": metric, "values": values, "confidence": confidence}


# ---- целостность каталога -------------------------------------------------

def test_every_core_metric_has_three_tiers():
    for metric in CORE_METRICS:
        tiers = sorted(d.tier for d in CATALOG[metric])
        assert tiers == [1, 2, 3], metric


def test_drill_ids_unique_across_catalog():
    ids = [d.drill_id for drills in CATALOG.values() for d in drills]
    assert len(ids) == len(set(ids))


def test_get_catalog_drill_roundtrip():
    cd = get_catalog_drill("consistency_t1_vt_ww5t_novice")
    assert cd is not None and cd.metric == "consistency" and cd.tier == 1


def test_get_catalog_drill_unknown_is_none():
    assert get_catalog_drill("does_not_exist") is None


def test_menu_lists_only_tier1_core_drills():
    menu = menu_for_prompt()
    assert "consistency_t1_vt_ww5t_novice" in menu
    assert "consistency_t2_vt_ww5t_intermediate" not in menu
    for metric in CORE_METRICS:
        t1 = next(d for d in CATALOG[metric] if d.tier == 1)
        assert t1.drill_id in menu


# ---- пороги рангов S5 -----------------------------------------------------

def test_voltaic_tier_close_thresholds():
    # верхний ранг тира = «закрыть тир»: Novice→Gold, Adv→Celestial
    assert get_catalog_drill(
        "consistency_t1_vt_ww5t_novice").rank_thresholds["gold"] == 1290
    assert get_catalog_drill(
        "bias_t2_vt_1w3ts_intermediate").rank_thresholds["master"] == 1380
    assert get_catalog_drill(
        "correction_t3_vt_pasu_advanced").rank_thresholds["celestial"] == 1240


def test_placement_has_no_voltaic_thresholds():
    for cd in CATALOG["placement"]:
        assert cd.rank_thresholds is None


# ---- критерии на реальной форме values ------------------------------------

def test_consistency_criterion_is_15pct_relative():
    c = build_criterion("consistency", {"mae_hu": 1.349, "std_hu": 0.7})
    assert c.value_key == "mae_hu" and c.comparator == "<"
    assert c.baseline == 1.349 and c.target == 1.147   # round(1.349*0.85, 3)


def test_placement_criterion_is_count_reduction():
    c = build_criterion("placement", {"total": 10, "below": 7, "mean_dy_hu": -1.4})
    assert c.value_key == "below" and c.comparator == "count_le"
    assert c.baseline == 7 and c.target == 2           # round(0.2*10)


def test_bias_criterion_halves_absolute_y():
    c = build_criterion("bias", {"y_bias_hu": -1.2, "x_bias_hu": 0.1})
    assert c.comparator == "<" and c.baseline == 1.2 and c.target == 0.6


def test_correction_criterion_is_directional_not_threshold():
    c = build_criterion("correction", {"flicks_analysed": 8, "x_overshoots": 5,
                                       "x_undershoots": 1, "y_overshoots": 0,
                                       "y_undershoots": 1})
    assert c.comparator == "direction" and c.target is None
    assert "перел" in c.text.lower()


def test_criterion_handles_missing_value():
    c = build_criterion("consistency", {"mae_hu": None})
    assert c.target is None and "клип" in c.text.lower()


# ---- сборка ---------------------------------------------------------------

def test_assemble_drill_pulls_name_from_catalog():
    sel = DrillSelection(priority=1,
                         drill_id="consistency_t1_vt_ww5t_novice",
                         rationale="повторяемость")
    drill = assemble_drill(sel, _finding("consistency", {"mae_hu": 1.349}))
    assert drill.name == get_catalog_drill(sel.drill_id).name
    assert drill.tier == 1 and drill.target_metric == "consistency"
    assert drill.criterion.baseline == 1.349
    assert drill.rationale == "повторяемость"


# ---- честность плана ------------------------------------------------------

def test_finalize_trims_to_two_when_no_diagnosis():
    findings = [_finding("placement", {"total": 5, "below": 4, "mean_dy_hu": -1},
                         confidence="hypothesis"),
                _finding("consistency", {"mae_hu": 1.3}, confidence="hypothesis"),
                _finding("bias", {"y_bias_hu": -0.9}, confidence="hypothesis"),
                _finding("correction", {"flicks_analysed": 2, "x_overshoots": 1,
                                        "x_undershoots": 0, "y_overshoots": 0,
                                        "y_undershoots": 0}, confidence="hypothesis")]
    sels = [
        DrillSelection(priority=1, drill_id="placement_t1_range_preaim_walk", rationale="a"),
        DrillSelection(priority=2, drill_id="consistency_t1_vt_ww5t_novice", rationale="b"),
        DrillSelection(priority=3, drill_id="bias_t1_vt_1w4ts_novice", rationale="c"),
        DrillSelection(priority=4, drill_id="correction_t1_vt_pasu_novice", rationale="d"),
    ]
    plan = finalize_plan(sels, findings)
    assert len(plan.drills) == 2
    assert [d.priority for d in plan.drills] == [1, 2]
    assert plan.extra_caveats and "клип" in plan.extra_caveats[0].lower()


def test_finalize_keeps_all_when_diagnosis_present():
    findings = [_finding("consistency", {"mae_hu": 1.3}, confidence="diagnosis"),
                _finding("bias", {"y_bias_hu": -0.9}, confidence="hypothesis")]
    sels = [
        DrillSelection(priority=2, drill_id="bias_t1_vt_1w4ts_novice", rationale="b"),
        DrillSelection(priority=1, drill_id="consistency_t1_vt_ww5t_novice", rationale="a"),
    ]
    plan = finalize_plan(sels, findings)
    assert [d.priority for d in plan.drills] == [1, 2]   # отсортировано
    assert plan.extra_caveats == []


def test_finalize_adds_cta_when_no_diagnosis_without_trim():
    # две гипотезы, урезать нечего — но CTA «запиши ещё клип» всё равно нужен
    findings = [_finding("consistency", {"mae_hu": 1.3}, confidence="hypothesis"),
                _finding("bias", {"y_bias_hu": -0.9}, confidence="hypothesis")]
    sels = [
        DrillSelection(priority=1, drill_id="consistency_t1_vt_ww5t_novice", rationale="a"),
        DrillSelection(priority=2, drill_id="bias_t1_vt_1w4ts_novice", rationale="b"),
    ]
    plan = finalize_plan(sels, findings)
    assert len(plan.drills) == 2                       # ничего не урезано
    assert plan.extra_caveats and "клип" in plan.extra_caveats[0].lower()
    assert "сокращён" not in plan.extra_caveats[0]     # не урезали — не ври


def test_finalize_skips_selection_without_finding():
    findings = [_finding("consistency", {"mae_hu": 1.3}, confidence="diagnosis")]
    sels = [DrillSelection(priority=1, drill_id="bias_t1_vt_1w4ts_novice", rationale="b")]
    plan = finalize_plan(sels, findings)
    assert plan.drills == []
