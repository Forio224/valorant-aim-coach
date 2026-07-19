# -*- coding: utf-8 -*-
"""Тесты детерминированного каталога дриллов Voltaic S5 (Фаза 1)."""
from coach.drill_catalog import (CATALOG, FinalizedPlan, assemble_drill,
                                 build_criterion, finalize_plan,
                                 get_catalog_drill, menu_drill_ids,
                                 menu_for_prompt)
from coach.schema import DrillSelection

CORE_METRICS = {"placement", "consistency", "bias", "correction"}


def _finding(metric, values, confidence="diagnosis"):
    return {"metric": metric, "values": values, "confidence": confidence}


# ---- целостность каталога -------------------------------------------------

def test_every_core_metric_has_three_tiers():
    # с Фазы 4 у метрик параллельные ветки (kovaaks + in-game) — важно, что
    # каждая метрика покрывает все три тира, а не что дриллов ровно три
    for metric in CORE_METRICS:
        tiers = set(d.tier for d in CATALOG[metric])
        assert tiers == {1, 2, 3}, metric


def test_drill_ids_unique_across_catalog():
    ids = [d.drill_id for drills in CATALOG.values() for d in drills]
    assert len(ids) == len(set(ids))


def test_get_catalog_drill_roundtrip():
    cd = get_catalog_drill("consistency_t1_vt_ww5t_novice")
    assert cd is not None and cd.metric == "consistency" and cd.tier == 1


def test_get_catalog_drill_unknown_is_none():
    assert get_catalog_drill("does_not_exist") is None


def test_menu_lists_only_tier1_core_drills():
    # дефолт (платформа не указана) = in-game меню: kovaaks исключён
    menu = menu_for_prompt()
    assert "consistency_t1_vt_ww5t_novice" not in menu
    assert "consistency_ingame_t1_range_tempo" in menu
    assert "consistency_t2_vt_ww5t_intermediate" not in menu
    # явный kovaaks возвращает тренажёрные tier-1 в меню
    kovaaks_menu = menu_for_prompt("kovaaks")
    assert "consistency_t1_vt_ww5t_novice" in kovaaks_menu
    assert "consistency_t2_vt_ww5t_intermediate" not in kovaaks_menu


# ---- Фаза 4: меню по training_platform ------------------------------------

def test_ingame_menu_is_exactly_four_and_kovaaks_free():
    for platform in ("ingame", None):
        ids = menu_drill_ids(platform)
        assert len(ids) == 4
        drills = [get_catalog_drill(i) for i in ids]
        assert all(d.platform != "kovaaks" for d in drills)
        # анти-сирота: у КАЖДОЙ из 4 метрик есть tier-1 вариант (bias не выпадает)
        assert {d.metric for d in drills} == set(CORE_METRICS)


def test_kovaaks_menu_is_exactly_seven():
    # placement 1 + consistency 2 + bias 2 + correction 2 — только при явном kovaaks
    ids = menu_drill_ids("kovaaks")
    assert len(ids) == 7


def test_old_drill_ids_untouched():
    # история 2B ключуется на id — переименование рвёт её
    for old in ("consistency_t1_vt_ww5t_novice", "bias_t1_vt_1w4ts_novice",
                "correction_t1_vt_pasu_novice", "placement_t1_range_preaim_walk"):
        assert get_catalog_drill(old) is not None


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


# --- Внешний гейт тира (KovaaK's S5) -----------------------------------------
from coach.drill_catalog import tier_threshold  # noqa: E402


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


# --- Внешние числа в финальном Drill -----------------------------------------

_EXTERNAL_DRILL = {"source": "kovaaks_webapp_unofficial", "season": "S5",
                   "fetched_at": "x", "tiers_failed": [],
                   "tiers": {"novice": {"overall_rank": 1,
                                        "benchmark_progress": 0.2,
                                        "scenarios": {"VT Pasu Novice S5": {
                                            "score": 812, "scenario_rank": 2,
                                            "rank_maxes": [555, 660, 745, 800]}}}}}


def test_assemble_drill_carries_external_numbers():
    selection = DrillSelection(priority=1,
                               drill_id="correction_t1_vt_pasu_novice",
                               rationale="r")
    finding = {"metric": "correction", "confidence": "diagnosis", "values": {}}
    plan = finalize_plan([selection], [finding],
                         external_benchmark=_EXTERNAL_DRILL)
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
