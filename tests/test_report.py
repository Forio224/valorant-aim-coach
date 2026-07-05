"""Stage 6 tests: evidence-tagged JSON contract — the bridge to the VLM coach.

Done-when: the portrait serialises to JSON where EVERY finding carries
frame/episode evidence references, so Phase B has facts to cite, not invent.
"""

import json
from pathlib import Path

import pytest

from aim_metrics import Head
from engine.clip_context import ClipContext
from engine.episodes import episodes_for_gt, segment_episodes
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
    assert {e["frame"] for e in placement["evidence"]} == \
        {ep.start_frame for ep in episodes}


def test_correction_evidence_points_at_the_flip_frame():
    ctx, samples, episodes = overshoot_clip()
    report = build_report(ctx, samples, episodes)
    correction = next(f for f in report["findings"] if f["metric"] == "correction")
    flip_frames = [e["frame"] for e in correction["evidence"]
                   if "перелёт" in e["note"].lower()]
    assert 7 in flip_frames                  # known synthetic overshoot frame


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
