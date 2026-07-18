"""Stage 6 tests: evidence-tagged JSON contract — the bridge to the VLM coach.

Done-when: the portrait serialises to JSON where EVERY finding carries
frame/episode evidence references, so Phase B has facts to cite, not invent.
"""

import json
from pathlib import Path

import pytest

from aim_metrics import Head
from engine.attribution import attribute_targets
from engine.clip_context import ClipContext
from engine.episodes import Episode, episodes_for_gt, segment_episodes
from engine.geometry import MIN_HEAD_PX, pick_target, sample_frame
from engine.metrics.consistency import compute_consistency
from engine.metrics.placement import PLACEMENT_MAX_BIRTH_HU
from engine.report import build_report, report_to_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRIEND_XML = PROJECT_ROOT / "dataset1" / "clip3.xml"
H = 20.0


def make_ctx(player_id="p1", clip_id="c1", frame_count=600) -> ClipContext:
    return ClipContext(player_id=player_id, clip_id=clip_id, fps=60.0,
                       width=1920, height=1080, frame_count=frame_count)


def overshoot_clip():
    """One flick with an X overshoot at a known frame + one hold episode."""
    frames: dict = {}
    dx = [20, 17, 14, 11, 8, 5, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 8
    for i, d in enumerate(dx):
        frames.setdefault(i, []).append(Head(960.0 + d * H, 540.0, height_px=H))
    for i in range(100, 130):                       # hold, born below-aim 1 HU
        frames.setdefault(i, []).append(Head(960.0, 520.0, height_px=H))
    ctx = make_ctx()
    episodes = segment_episodes(frames, ctx)
    samples = [s for ep in episodes for s in ep.samples]
    return ctx, samples, episodes


# ── Contract shape ───────────────────────────────────────────────────────────


def test_report_has_versioned_schema_and_clip_context():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)
    assert report["schema_version"]
    assert report["clip"]["player_id"] == "p1"
    assert report["clip"]["fps"] == 60.0
    assert report["clip"]["frame_count"] == 600


def test_episodes_block_carries_frames_and_seconds():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)
    assert len(report["episodes"]) == len(episodes)
    ep0 = report["episodes"][0]
    assert ep0["start_frame"] == 0 and ep0["start_s"] == 0.0
    assert ep0["kind"] == "flick"
    assert "birth" in ep0 and "dy_hu" in ep0["birth"]


# ── Done-when: every finding carries evidence ────────────────────────────────


def test_every_finding_with_data_has_evidence():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)
    metrics = {f["metric"] for f in report["findings"]}
    assert {"placement", "consistency", "bias", "correction"} <= metrics
    for finding in report["findings"]:
        assert finding["statement"]
        assert finding["confidence"] in ("diagnosis", "hypothesis", "insufficient")
        assert finding["evidence"], f"finding {finding['metric']} has no evidence"


def test_evidence_frames_lie_within_the_clip():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)
    for finding in report["findings"]:
        for item in finding["evidence"]:
            frame = item.get("frame", item.get("frame_start"))
            assert frame is not None
            assert 0 <= frame < ctx.frame_count
            assert "episode" in item and "note" in item


def test_placement_evidence_anchors_to_birth_frames():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)
    placement = next(f for f in report["findings"] if f["metric"] == "placement")
    # Гейт пре-айма: улики только для появлений в зоне (далёкий флик отсеян).
    gated_births = {ep.start_frame for ep in episodes
                    if ep.samples[0].radial_hu <= PLACEMENT_MAX_BIRTH_HU}
    assert {e["frame"] for e in placement["evidence"]} == gated_births


def test_correction_evidence_points_at_the_flip_frame():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)
    correction = next(f for f in report["findings"] if f["metric"] == "correction")
    flip_frames = [e["frame"] for e in correction["evidence"]
                   if "перелёт" in e["note"].lower()]
    assert 7 in flip_frames                  # known synthetic overshoot frame


# ── Input-space (Фаза 4): cm/360 в clip-блоке, см-эквивалент перелёта ────────


def _ctx_with_edpi(edpi=280.0) -> ClipContext:
    return ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                       width=1920, height=1080, frame_count=600, edpi=edpi)


def test_clip_block_carries_cm_per_360_and_reason():
    _, samples, episodes = overshoot_clip()
    with_edpi = build_report(_ctx_with_edpi(), samples, episodes)["clip"]
    assert with_edpi["cm_per_360"] == pytest.approx(46.65, abs=0.01)
    assert with_edpi["cm_unavailable_reason"] is None
    without = build_report(make_ctx(), samples, episodes)["clip"]
    assert without["cm_per_360"] is None
    assert without["cm_unavailable_reason"] == "нет eDPI"


def test_correction_values_have_cm_equiv_median_or_none():
    _, samples, episodes = overshoot_clip()
    with_edpi = build_report(_ctx_with_edpi(), samples, episodes)
    corr = next(f for f in with_edpi["findings"] if f["metric"] == "correction")
    assert "flick_overshoot_cm_equiv_median" in corr["values"]
    val = corr["values"]["flick_overshoot_cm_equiv_median"]
    assert val is None or isinstance(val, float)
    without = build_report(make_ctx(), samples, episodes)
    corr2 = next(f for f in without["findings"] if f["metric"] == "correction")
    assert corr2["values"]["flick_overshoot_cm_equiv_median"] is None
    report_to_json(without)                    # сериализация не падает


# ── Serialisation ────────────────────────────────────────────────────────────


def test_json_round_trips_and_bans_nan():
    ctx, samples, episodes = overshoot_clip()
    text = report_to_json(build_report(ctx, samples, episodes))
    parsed = json.loads(text)
    assert parsed["schema_version"]
    assert "NaN" not in text


def test_empty_clip_serialises_without_nan():
    ctx = make_ctx()
    text = report_to_json(build_report(ctx, [], []))
    assert json.loads(text)["episodes"] == []


def test_profile_attached_when_given():
    from engine.profile_store import aggregate_profile
    ctx, samples, episodes = overshoot_clip()
    from engine.profile_store import build_clip_record
    doc = {"player_id": "p1",
           "clips": {"c1": build_clip_record(ctx, samples, episodes)}}
    report = build_report(ctx, samples, episodes,
                          profile=aggregate_profile(doc))
    assert report["profile"]["player_id"] == "p1"
    assert report["profile"]["confidence"] in ("diagnosis", "hypothesis")


# ── Атрибуция цели: разброс без скачка смены цели + мета в consistency ────────


def _episode(track_id, points, ctx, height=20.0, duel_hu=3.0):
    """Синтетический Episode с чистой идентичностью: points = (frame, cx, cy)."""
    samples = tuple(sample_frame(f, Head(cx, cy, height), ctx.crosshair)
                    for f, cx, cy in points)
    return Episode(track_id=track_id, start_frame=points[0][0],
                   end_frame=points[-1][0], samples=samples, kind="flick",
                   distance_bucket="mid", multi_enemy=True, multi_from_frame=0,
                   duel_frames=sum(1 for s in samples if s.radial_hu <= duel_hu),
                   peak_closing_speed_hu_s=0.0)


def _naive_samples(episodes, ctx):
    """Старое поведение: ближайшая к прицелу голова на каждом кадре (без identity)."""
    frames: dict = {}
    for ep in episodes:
        for s in ep.samples:
            hu = max(s.head_height_px, MIN_HEAD_PX)
            frames.setdefault(s.frame_idx, []).append(
                Head(ctx.crosshair[0] + s.dx_hu * hu,
                     ctx.crosshair[1] + s.dy_hu * hu, s.head_height_px))
    out = []
    for f in sorted(frames):
        out.append(sample_frame(f, pick_target(frames[f], ctx.crosshair),
                                ctx.crosshair))
    return out


def test_attribution_lowers_consistency_spread_and_reports_meta():
    """Цель A удерживается; сосед B ныряет через дуэль собственным движением.
    Наивная «ближайшая» ловит B и вздувает std; атрибуция держит A → разброс
    ниже. И consistency.values несёт switches/contested_frames/camera_confidence."""
    ctx = make_ctx()
    a = _episode(1, [(f, 1018.0, 540.0) for f in range(10)], ctx)   # 2.9 HU, держим
    c = _episode(3, [(f, 1260.0, 540.0) for f in range(10)], ctx)   # 15 HU, статичен
    bx = [1180, 1140, 1060, 1000, 980, 1000, 1060, 1140, 1180, 1180]
    b = _episode(2, [(f, float(x), 540.0) for f, x in enumerate(bx)], ctx)
    eps = [a, b, c]

    attribution = attribute_targets(eps, ctx)
    samples = [s for s in attribution.samples if s.track_id is not None]
    std_attr = compute_consistency(samples).std_hu
    std_naive = compute_consistency(_naive_samples(eps, ctx)).std_hu
    assert std_attr < std_naive                  # скачок смены цели исключён

    report = build_report(ctx, samples, eps, attribution=attribution)
    cons = next(f for f in report["findings"] if f["metric"] == "consistency")
    assert cons["values"]["switches"] == attribution.switches
    assert cons["values"]["contested_frames"] == attribution.contested_frames
    assert cons["values"]["camera_confidence"] == "diagnosis"   # 3 головы


def test_target_choices_block_is_top_level_and_schema_is_current():
    """target_choices — top-level факты выбора (без вердикта), схема 1.3."""
    ctx = make_ctx()
    a = _episode(1, [(f, 1018.0, 540.0) for f in range(10)], ctx)
    bx = [1180, 1140, 1060, 1000, 980, 1000, 1060, 1140, 1180, 1180]
    b = _episode(2, [(f, float(x), 540.0) for f, x in enumerate(bx)], ctx)
    c = _episode(3, [(f, 1260.0, 540.0) for f in range(10)], ctx)
    eps = [a, b, c]
    attribution = attribute_targets(eps, ctx)
    samples = [s for s in attribution.samples if s.track_id is not None]
    report = build_report(ctx, samples, eps, attribution=attribution)

    assert report["schema_version"] == "1.3"
    assert isinstance(report["target_choices"], list) and report["target_choices"]
    fields = {"track_id", "from_frame", "to_frame", "chosen_at_radial_hu",
              "head_height_px", "lateral_speed_hu_s", "switch_cost_frames"}
    for tc in report["target_choices"]:
        assert fields <= set(tc)
    # это НЕ находка: у target_choices нет критериев/дриллов/вердикта
    assert all(f["metric"] != "target_choices" for f in report["findings"])


def test_target_choices_empty_without_attribution():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)      # без attribution
    assert report["schema_version"] == "1.3"
    assert report["target_choices"] == []


# ── Real clip ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_report_on_real_clip_is_fully_evidenced():
    ctx = make_ctx(player_id="friend", clip_id="clip3", frame_count=700)
    episodes = episodes_for_gt(str(FRIEND_XML), ctx)
    samples = [s for ep in episodes for s in ep.samples]
    report = json.loads(report_to_json(build_report(ctx, samples, episodes)))
    assert len(report["episodes"]) == 5
    for finding in report["findings"]:
        assert finding["evidence"]
        for item in finding["evidence"]:
            frame = item.get("frame", item.get("frame_start"))
            assert 0 <= frame <= 700
