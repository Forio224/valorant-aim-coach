"""Stage 6: evidence-tagged JSON contract — the bridge to the VLM coach.

The metric layer is a supplier of CITABLE FACTS: every finding carries
references to concrete frames/episodes («кадр 47: прицел 0.8 HU ниже, враг
пикнул слева»), so Phase B formulates advice from evidence instead of
inventing. Schema is versioned; NaN is banned at serialisation time
(allow_nan=False) so a malformed portrait fails fast, not downstream.
"""

import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from statistics import median
from typing import List, Optional, Sequence

from engine.geometry import DEFAULT_DUEL_HU, FrameSample, compute_passport
from engine.attribution import AttributionResult
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.input_space import cm_per_360, cm_unavailable_reason, hu_to_cm_equiv
from engine.version import METRICS_VERSION
from engine.metrics.consistency import _DIAGNOSIS_TEXT, compute_consistency
from engine.metrics.correction import _AXIS_LABELS, compute_correction
from engine.metrics.drill_progress import compute_drill_progress
from engine.metrics.flick_phase import compute_flick_phases
from engine.metrics.placement import compute_placement
from engine.profile_store import (
    MIN_DUEL_FRAMES_FOR_DIAGNOSIS,
    MIN_EPISODES_FOR_DIAGNOSIS,
    PlayerProfile,
)

SCHEMA_VERSION = "1.3"
MIN_FLICKS_FOR_DIAGNOSIS = 6

_VERTICAL_NOTES = {"below": "прицел ниже линии головы",
                   "above": "прицел выше линии головы",
                   "on_line": "прицел на линии головы"}


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    """Round for the contract; NaN becomes None so JSON stays valid."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(x, digits)


def _confidence(n: int, min_n: int) -> str:
    if n == 0:
        return "insufficient"
    return "diagnosis" if n >= min_n else "hypothesis"


def _geom(sample: FrameSample) -> dict:
    """Schema 1.1: anchor-frame geometry on every evidence entry, so the head
    box is reconstructible in pixels (crosshair = fixed screen centre) without
    resampling the video."""
    return {"dx_hu": _r(sample.dx_hu), "dy_hu": _r(sample.dy_hu),
            "head_height_px": _r(sample.head_height_px, 2)}


def _sample_at(ep: Episode, frame_idx: int) -> FrameSample:
    return next(s for s in ep.samples if s.frame_idx == frame_idx)


# ── Blocks ───────────────────────────────────────────────────────────────────

def _episodes_block(episodes: Sequence[Episode], ctx: ClipContext) -> List[dict]:
    block = []
    for i, ep in enumerate(episodes, start=1):
        birth = ep.samples[0]
        block.append({
            "index": i,
            "track_id": ep.track_id,
            "start_frame": ep.start_frame,
            "end_frame": ep.end_frame,
            "start_s": _r(ctx.frame_to_seconds(ep.start_frame), 2),
            "end_s": _r(ctx.frame_to_seconds(ep.end_frame), 2),
            "kind": ep.kind,
            "distance_bucket": ep.distance_bucket,
            "multi_from_frame": ep.multi_from_frame,
            "duel_frames": ep.duel_frames,
            "peak_closing_speed_hu_s": _r(ep.peak_closing_speed_hu_s, 1),
            "birth": {"dx_hu": _r(birth.dx_hu), "dy_hu": _r(birth.dy_hu),
                      "radial_hu": _r(birth.radial_hu)},
        })
    return block


def _duel_window_evidence(episodes: Sequence[Episode], ctx: ClipContext,
                          duel_hu: float) -> List[dict]:
    """Frame ranges where the player was actually duelling — the data behind
    every distribution-shaped metric (consistency, bias)."""
    evidence = []
    for i, ep in enumerate(episodes, start=1):
        duel = [s for s in ep.samples if s.radial_hu <= duel_hu]
        if not duel:
            continue
        evidence.append({
            "frame_start": duel[0].frame_idx,
            "frame_end": duel[-1].frame_idx,
            "time_s": _r(ctx.frame_to_seconds(duel[0].frame_idx), 2),
            "episode": i,
            "note": f"дуэльное окно ({len(duel)} кадров, radial<={duel_hu:g} HU)",
            **_geom(duel[0]),
        })
    return evidence


def _placement_finding(episodes: Sequence[Episode], ctx: ClipContext) -> dict:
    rep = compute_placement(episodes, ctx)
    evidence = []
    for v in rep.verdicts:
        side = "слева" if v.dx_hu < 0 else "справа"
        birth = episodes[v.episode_index - 1].samples[0]
        evidence.append({
            "frame": v.frame_idx,
            "time_s": _r(v.time_s, 2),
            "episode": v.episode_index,
            "note": (f"появление врага {side} (dx {v.dx_hu:+.2f} HU): "
                     f"{_VERTICAL_NOTES[v.vertical]} (dy {v.dy_hu:+.2f} HU)"),
            **_geom(birth),
        })
    return {
        "metric": "placement",
        "statement": (f"Пре-айм: {rep.n_below} из {rep.total_gated} появлений"
                      f" в зоне (≤{rep.max_birth_hu:g} HU) — прицел ниже линии"
                      f" головы (≥{rep.band_hu:g} HU); выше: {rep.n_above};"
                      f" на линии: {rep.n_on_line}"
                      f" (всего появлений: {rep.total_seen})"),
        # total = total_gated: вход build_criterion и уверенности считается от
        # отсеянного множества (пре-айм честно опускается до гипотезы там, где
        # уверенность держалась на не-пре-айм появлениях).
        "values": {"total": rep.total_gated, "below": rep.n_below,
                   "above": rep.n_above, "on_line": rep.n_on_line,
                   "band_hu": rep.band_hu, "mean_dy_hu": _r(rep.mean_dy_hu),
                   "median_dy_hu": _r(rep.median_dy_hu),
                   "total_seen": rep.total_seen, "total_gated": rep.total_gated},
        "confidence": _confidence(rep.total_gated,
                                  MIN_EPISODES_FOR_DIAGNOSIS),
        "evidence": evidence,
    }


def _consistency_finding(samples: Sequence[FrameSample], duel_evidence: List[dict],
                         duel_hu: float,
                         attribution: Optional[AttributionResult] = None) -> dict:
    rep = compute_consistency(samples, duel_hu=duel_hu)
    values = {"duel_frames": rep.duel_frames,
              "mae_hu": _r(rep.duel_mae_hu), "std_hu": _r(rep.std_hu),
              "iqr_hu": _r(rep.iqr_hu), "p95_hu": _r(rep.p95_hu),
              "diagnosis": rep.diagnosis}
    if attribution is not None:
        # Движок честно показывает, сколько кадров было спорных, вместо того
        # чтобы молча смешивать врагов (Фаза 3, атрибуция цели).
        values["switches"] = attribution.switches
        values["contested_frames"] = attribution.contested_frames
        values["camera_confidence"] = attribution.camera_confidence
    return {
        "metric": "consistency",
        "statement": _DIAGNOSIS_TEXT[rep.diagnosis],
        "values": values,
        "confidence": _confidence(rep.duel_frames,
                                  MIN_DUEL_FRAMES_FOR_DIAGNOSIS),
        "evidence": duel_evidence,
    }


def _bias_finding(samples: Sequence[FrameSample], duel_evidence: List[dict],
                  duel_hu: float) -> dict:
    p = compute_passport(list(samples), duel_hu=duel_hu)
    y, x = _r(p.y_bias_hu), _r(p.x_bias_hu)
    statement = ("Биасы в дуэли: "
                 + (f"Y {y:+.3f} HU (минус = прицел ниже голов), X {x:+.3f} HU"
                    if y is not None else "нет дуэльных кадров"))
    return {
        "metric": "bias",
        "statement": statement,
        "values": {"y_bias_hu": y, "x_bias_hu": x,
                   "x_abs_hu": _r(p.x_abs_hu), "y_abs_hu": _r(p.y_abs_hu),
                   "duel_frames": p.duel_frames},
        "confidence": _confidence(p.duel_frames, MIN_DUEL_FRAMES_FOR_DIAGNOSIS),
        "evidence": duel_evidence,
    }


def _correction_finding(episodes: Sequence[Episode], ctx: ClipContext,
                        duel_hu: float) -> dict:
    rep = compute_correction(episodes, ctx, duel_hu=duel_hu)
    ph = compute_flick_phases(episodes, ctx)
    settle_ms = (None if ph.settle_time_frames_median is None
                 else round(1000 * ph.settle_time_frames_median / ctx.fps))
    evidence = []
    for v in rep.verdicts:
        ep = episodes[v.episode_index - 1]
        events = [(axis, kind, frame) for axis, kind, frame in
                  (("X", v.x, v.x_evidence_frame), ("Y", v.y, v.y_evidence_frame))
                  if kind != "clean"]
        if not events:                       # clean flicks are evidence too
            evidence.append({"frame": v.start_frame, "time_s": _r(v.time_s, 2),
                             "episode": v.episode_index,
                             "note": "чистый флик: без перелёта и недолёта",
                             **_geom(_sample_at(ep, v.start_frame))})
        for axis, kind, frame in events:
            evidence.append({
                "frame": frame,
                "time_s": _r(ctx.frame_to_seconds(frame), 2),
                "episode": v.episode_index,
                "note": f"{axis}: {_AXIS_LABELS[kind]}",
                **_geom(_sample_at(ep, frame)),
            })
    # фаз-улики: истинный перелёт через центр (пик доводки) — кадр иной, чем
    # sign-flip у correction, поэтому доклеиваем отдельной уликой, а не дублем
    for p in ph.phases:
        if p.overshoot_evidence_frame is None:
            continue
        pep = episodes[p.episode_index - 1]
        evidence.append({
            "frame": p.overshoot_evidence_frame,
            "time_s": _r(ctx.frame_to_seconds(p.overshoot_evidence_frame), 2),
            "episode": p.episode_index,
            "note": (f"истинный перелёт через центр {p.flick_overshoot_hu} HU"
                     f" (пик доводки)"),
            **_geom(_sample_at(pep, p.overshoot_evidence_frame)),
        })
    # см-эквивалент перелёта: те же usable-флики, что HU-медиана; конверсия по
    # высоте головы на кадре улики перелёта. 0-перелёт конвертируется в 0 см.
    cm_vals = []
    for p in ph.phases:
        if not p.settled or p.flick_overshoot_hu is None:
            continue
        if p.overshoot_evidence_frame is None:
            cm_vals.append(0.0 if p.flick_overshoot_hu == 0 else None)
            continue
        pep = episodes[p.episode_index - 1]
        hh = _sample_at(pep, p.overshoot_evidence_frame).head_height_px
        cm_vals.append(hu_to_cm_equiv(p.flick_overshoot_hu, hh, ctx))
    cm_known = [v for v in cm_vals if v is not None]
    cm_median = _r(median(cm_known), 2) if cm_known else None
    return {
        "metric": "correction",
        "statement": (f"Коррекция на фликах ({rep.flicks_analysed}): X перелёт"
                      f" {rep.x_overshoots}/недолёт {rep.x_undershoots},"
                      f" Y перелёт {rep.y_overshoots}/недолёт {rep.y_undershoots}."
                      f" {rep.symmetry_note}"),
        "values": {"flicks_total": rep.flicks_total,
                   "flicks_analysed": rep.flicks_analysed,
                   "flicks_sparse": rep.flicks_sparse,
                   "x_overshoots": rep.x_overshoots,
                   "x_undershoots": rep.x_undershoots,
                   "y_overshoots": rep.y_overshoots,
                   "y_undershoots": rep.y_undershoots,
                   "flick_overshoot_hu_median": ph.flick_overshoot_hu_median,
                   "settle_time_frames_median": ph.settle_time_frames_median,
                   "settle_time_ms_median": settle_ms,
                   "settle_jitter_hu_median": ph.settle_jitter_hu_median,
                   "flick_overshoot_cm_equiv_median": cm_median,
                   "correction_path_hu_median": ph.correction_path_hu_median,
                   "flicks_arrived": ph.flicks_arrived,
                   "flicks_settled": ph.flicks_settled,
                   "flicks_jitter_n": ph.flicks_jitter_n,
                   "phase_confidence": ph.phase_confidence},
        "confidence": _confidence(rep.flicks_analysed, MIN_FLICKS_FOR_DIAGNOSIS),
        "caveat": ("смена знака может быть стрейфом врага — прокси-метрика по"
                   " output-space, не механика мыши"
                   + ("; см — эквивалент хода мыши, не измерение (стрейф врага"
                      " неотделим); валидно для стрельбы с бедра — Operator в"
                      " прицеле ≈ 2.5×, сигнала о зуме в данных нет"
                      if cm_median is not None else "")),
        "evidence": evidence,
    }


def _clip_block(ctx: ClipContext) -> dict:
    block = asdict(ctx)
    # Input-space (Фаза 4): sens/eDPI конвертируются в физику руки. Причины
    # отсутствия раздельны: cm/360 живёт на stretched res, cm-эквивалент — нет.
    block["cm_per_360"] = _r(cm_per_360(ctx.edpi), 2)
    block["cm_unavailable_reason"] = cm_unavailable_reason(ctx)
    return block


# ── Entry points ─────────────────────────────────────────────────────────────

def build_report(ctx: ClipContext, samples: Sequence[FrameSample],
                 episodes: Sequence[Episode],
                 duel_hu: float = DEFAULT_DUEL_HU,
                 profile: Optional[PlayerProfile] = None,
                 drill_history: Sequence = (),
                 attribution: Optional[AttributionResult] = None) -> dict:
    """The full evidence-tagged portrait of one clip (+ longitudinal profile).

    `attribution` (Фаза 3): когда `samples` пришли из `attribute_targets`,
    consistency честно доносит switches/contested_frames/camera_confidence.
    """
    duel_evidence = _duel_window_evidence(episodes, ctx, duel_hu)
    report = {
        "schema_version": SCHEMA_VERSION,
        # Методика измерения: 2B-петля прогресса фильтрует историю по этому
        # полю, иначе смена методики Фазы 3 посчиталась бы прогрессом игрока.
        "metrics_version": METRICS_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "clip": _clip_block(ctx),
        "episodes": _episodes_block(episodes, ctx),
        "findings": [
            _placement_finding(episodes, ctx),
            _consistency_finding(samples, duel_evidence, duel_hu, attribution),
            _bias_finding(samples, duel_evidence, duel_hu),
            _correction_finding(episodes, ctx, duel_hu),
        ],
    }
    # Схема 1.2: факты выбора цели top-level блоком, НЕ находкой — у находок
    # критерии и дриллы, а здесь вердикта нет и быть не должно (база для будущей
    # нормативной фазы, когда появится сигнал об угрозе).
    report["target_choices"] = (
        [asdict(c) for c in attribution.choices] if attribution is not None
        else [])
    report["drill_progress"] = compute_drill_progress(report["findings"],
                                                      list(drill_history))
    if profile is not None:
        report["profile"] = asdict(profile)
    return report


def report_to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
