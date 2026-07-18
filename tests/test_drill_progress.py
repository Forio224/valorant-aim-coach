# -*- coding: utf-8 -*-
"""Петля прогресса на engine-сигнале (Фаза 2B) — синтетика, без БД."""
from engine.metrics.drill_progress import compute_drill_progress


def _finding(metric, values, confidence="diagnosis"):
    return {"metric": metric, "values": values, "confidence": confidence}


def _snap(clip_time, clip_id, assignments, findings):
    return {"clip_time": clip_time, "clip_id": clip_id,
            "assignments": assignments, "findings": findings}


def _mae_snap(t, cid, mae, conf="diagnosis", flagged=True):
    return _snap(t, cid, {"consistency": "consistency_t1_vt_ww5t_novice"} if flagged
                else {}, {"consistency": _finding("consistency", {"mae_hu": mae}, conf)})


# ---- ретроспективная пустота -------------------------------------------------

def test_first_clip_no_history_empty():
    findings = [_finding("consistency", {"mae_hu": 5.0})]
    assert compute_drill_progress(findings, []) == []


def test_metric_never_flagged_not_reported():
    # история есть, но consistency ни разу не флагнута → не репортим
    history = [_snap(1, "c1", {}, {"consistency": _finding("consistency", {"mae_hu": 5.0})})]
    findings = [_finding("consistency", {"mae_hu": 4.0})]
    assert compute_drill_progress(findings, history) == []


# ---- кумулятивная дельта (не clip-to-clip) -----------------------------------

def test_cumulative_delta_from_series_anchor():
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.6),
               _mae_snap(3, "c3", 4.4)]
    findings = [_finding("consistency", {"mae_hu": 4.2})]   # текущий клип
    rec = compute_drill_progress(findings, history)[0]
    assert rec["anchor_clip_id"] == "c1" and rec["anchor_value"] == 5.0
    assert rec["current_value"] == 4.2
    assert rec["delta"] == -0.8              # 4.2 − 5.0, кумулятив, НЕ −0.2
    assert rec["direction"] == "improved"
    assert rec["series_len"] == 3
    assert rec["order_uncertain"] is True
    assert rec["drill_id"] == "consistency_t1_vt_ww5t_novice"


# ---- отсутствие дрилла НЕ рвёт серию (Баг A) ---------------------------------

def test_drill_absence_does_not_break_series():
    # clip2 не флагнут (топ-2-трим), но слабость не разрешена → anchor держится
    history = [_mae_snap(1, "c1", 5.0),
               _mae_snap(2, "c2", 4.9, flagged=False),
               _mae_snap(3, "c3", 4.8)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.7})], history)[0]
    assert rec["anchor_clip_id"] == "c1" and rec["delta"] == -0.3


# ---- разрыв по резолюции + новый anchor ---------------------------------------

def test_resolution_breaks_series_and_reanchors():
    # target на c1 = 5.0*0.85 = 4.25; c2 mae 4.0 < 4.25 → резолюция; c3 рефлаг
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.0),
               _mae_snap(3, "c3", 6.0)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 5.5})], history)[0]
    assert rec["anchor_clip_id"] == "c3" and rec["anchor_value"] == 6.0
    assert rec["delta"] == -0.5 and rec["direction"] == "improved"


def test_resolved_then_not_reflagged_drops_out():
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.0, flagged=False)]
    # разрешено на c2, дальше не флагнута → нет открытой серии
    assert compute_drill_progress([_finding("consistency", {"mae_hu": 3.9})], history) == []


def test_resolution_on_unassigned_clip_reanchors():
    # 2C-пиновка: резолюция засчитывается и на клипе БЕЗ назначенного дрилла
    # (c2 не флагнут, но mae 4.0 < target 4.25) — серия рвётся по резолюции,
    # не по присутствию дрилла; рефлаг на c3 открывает новую серию
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.0, flagged=False),
               _mae_snap(3, "c3", 6.0)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 5.5})],
                                 history)[0]
    assert rec["anchor_clip_id"] == "c3" and rec["anchor_value"] == 6.0


def test_resolution_requires_at_least_hypothesis():
    # c2 под target, но insufficient → НЕ резолюция, серия держит anchor c1
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.0, conf="insufficient"),
               _mae_snap(3, "c3", 4.5)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.4})], history)[0]
    assert rec["anchor_clip_id"] == "c1"


# ---- resolved_now ------------------------------------------------------------

def test_resolved_now_flag_on_current_clip():
    history = [_mae_snap(1, "c1", 5.0)]      # target 4.25
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.0})], history)[0]
    assert rec["resolved_now"] is True and rec["direction"] == "improved"


def test_under_target_but_insufficient_not_resolved_now():
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": 4.0}, "insufficient")], history)[0]
    assert rec["resolved_now"] is False and rec["confidence"] == "insufficient"


# ---- min-confidence ----------------------------------------------------------

def test_confidence_is_min_of_endpoints():
    history = [_mae_snap(1, "c1", 5.0, conf="hypothesis")]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": 4.8}, "diagnosis")], history)[0]
    assert rec["confidence"] == "hypothesis"     # min(hypothesis, diagnosis)


# ---- bias-abs ----------------------------------------------------------------

def test_bias_normalized_by_magnitude():
    def bsnap(t, cid, yb, conf="diagnosis"):
        return _snap(t, cid, {"bias": "bias_t1_vt_1w4ts_novice"},
                     {"bias": _finding("bias", {"y_bias_hu": yb}, conf)})
    history = [bsnap(1, "c1", -0.6)]        # baseline abs = 0.6
    # текущий +0.5 → |0.5| < 0.6 → improved (не «улучшение» из-за смены знака)
    rec = compute_drill_progress(
        [_finding("bias", {"y_bias_hu": 0.5})], history)[0]
    assert rec["anchor_value"] == 0.6 and rec["current_value"] == 0.5
    assert rec["direction"] == "improved" and rec["delta"] == -0.1


# ---- null current ------------------------------------------------------------

def test_null_current_value_insufficient():
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": None}, "insufficient")], history)[0]
    assert rec["delta"] is None and rec["direction"] == "insufficient"
    assert rec["confidence"] == "insufficient"


# ---- correction: единый anchor, вырожденец → skip ----------------------------

def _corr_snap(t, cid, vals, conf="diagnosis", flagged=True):
    return _snap(t, cid, {"correction": "correction_t1_vt_pasu_novice"} if flagged
                else {}, {"correction": _finding("correction", vals, conf)})


def test_correction_single_anchor_never_breaks():
    v = lambda xo: {"x_overshoots": xo, "x_undershoots": 0, "y_overshoots": 0,
                    "y_undershoots": 0, "flicks_analysed": 5}
    history = [_corr_snap(1, "c1", v(3)), _corr_snap(2, "c2", v(0)),   # count 0 не рвёт
               _corr_snap(3, "c3", v(2))]
    rec = compute_drill_progress([_finding("correction", v(1))], history)[0]
    assert rec["anchor_clip_id"] == "c1" and rec["anchor_value"] == 3.0
    assert rec["current_value"] == 1 and rec["delta"] == -2 and rec["direction"] == "improved"
    assert rec["resolved_now"] is False       # target=None у прокси


def test_correction_degenerate_anchor_skipped_as_insufficient():
    v0 = {"x_overshoots": 0, "x_undershoots": 0, "y_overshoots": 0,
          "y_undershoots": 0, "flicks_analysed": 4}
    history = [_corr_snap(1, "c1", v0)]        # anchor вырожден (count 0)
    rec = compute_drill_progress([_finding("correction", v0)], history)[0]
    assert rec["direction"] == "insufficient" and rec["delta"] is None


# ---- граница округления/точности ---------------------------------------------

def test_sub_hu_delta_not_collapsed_to_flat():
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.8})], history)[0]
    assert rec["delta"] == -0.2 and rec["direction"] == "improved"   # НЕ 0/flat


def test_current_exactly_on_target_stable_resolution():
    # anchor mae 5.0 → target 4.25; current ровно 4.25 при сырой «шумной» точности
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": 4.2500001})], history)[0]
    assert rec["current_value"] == 4.25          # нормировано в одно пространство
    assert rec["resolved_now"] is False          # 4.25 < 4.25 ложно (строгий <)


# ---- детерминированный порядок -----------------------------------------------

def test_records_sorted_by_core_metrics_order():
    history = [
        _snap(1, "c1", {"correction": "correction_t1_vt_pasu_novice",
                        "consistency": "consistency_t1_vt_ww5t_novice"},
              {"correction": _finding("correction",
                   {"x_overshoots": 2, "x_undershoots": 0, "y_overshoots": 0,
                    "y_undershoots": 0, "flicks_analysed": 5}),
               "consistency": _finding("consistency", {"mae_hu": 5.0})}),
    ]
    findings = [_finding("correction",
                    {"x_overshoots": 1, "x_undershoots": 0, "y_overshoots": 0,
                     "y_undershoots": 0, "flicks_analysed": 5}),
                _finding("consistency", {"mae_hu": 4.8})]
    recs = compute_drill_progress(findings, history)
    assert [r["metric"] for r in recs] == ["consistency", "correction"]


def test_build_report_emits_drill_progress_key():
    from engine.clip_context import ClipContext
    from engine.report import build_report
    ctx = ClipContext(player_id="p", clip_id="cur", fps=60.0,
                      width=1920, height=1080, frame_count=100)
    report = build_report(ctx, [], [])          # пустой клип, без истории
    assert report["drill_progress"] == []       # ключ есть, дефолт пустой
