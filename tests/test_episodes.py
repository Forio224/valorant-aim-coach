"""Stage 1 tests: episode segmentation (tracks -> tagged duel episodes).

Synthetic head trajectories with known answers; integration tests on the real
dataset1/clip2.xml GT labels.
"""

from pathlib import Path

import pytest

from aim_metrics import Head
from engine.clip_context import ClipContext
from engine.episodes import (
    Episode,
    episodes_for_gt,
    format_episodes,
    gt_tracks,
    segment_episodes,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_XML = PROJECT_ROOT / "dataset1" / "clip2.xml"
REAL_VIDEO = PROJECT_ROOT / "dataset1" / "clip2.mp4"

CENTRE = (960.0, 540.0)


def make_ctx(fps: float = 60.0) -> ClipContext:
    return ClipContext(player_id="p1", clip_id="c1", fps=fps,
                       width=1920, height=1080, frame_count=600)


def static_head(x: float, y: float, h: float = 20.0) -> Head:
    return Head(cx=x, cy=y, height_px=h)


def add_linear_run(frames: dict, start: int, n: int,
                   p0: tuple, p1: tuple, h: float = 20.0) -> None:
    """Append a head moving linearly from p0 to p1 over n frames."""
    for i in range(n):
        t = i / max(n - 1, 1)
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        frames.setdefault(start + i, []).append(static_head(x, y, h))


# ── Episode kinds ────────────────────────────────────────────────────────────


def test_flick_episode_detected():
    frames: dict = {}
    add_linear_run(frames, 0, 40, (1500.0, 540.0), CENTRE)   # close in
    add_linear_run(frames, 40, 10, CENTRE, CENTRE)           # sit on target
    eps = segment_episodes(frames, make_ctx())
    assert len(eps) == 1
    ep = eps[0]
    assert ep.kind == "flick"             # born far, got engaged
    assert ep.start_frame == 0
    assert ep.end_frame == 49
    assert len(ep.samples) == 50
    assert ep.duel_frames > 0
    assert ep.peak_closing_speed_hu_s > 0


def test_hold_episode_detected():
    frames: dict = {}
    add_linear_run(frames, 0, 30, (970.0, 545.0), (970.0, 545.0))
    eps = segment_episodes(frames, make_ctx())
    assert len(eps) == 1
    assert eps[0].kind == "hold"          # born already near the crosshair


def test_unengaged_episode_detected():
    frames: dict = {}
    add_linear_run(frames, 0, 30, (200.0, 200.0), (200.0, 200.0))
    eps = segment_episodes(frames, make_ctx())
    assert len(eps) == 1
    assert eps[0].kind == "unengaged"     # never entered the duel zone
    assert eps[0].duel_frames == 0


# ── Noise / gap handling ─────────────────────────────────────────────────────


def test_short_blip_dropped():
    frames: dict = {}
    add_linear_run(frames, 0, 3, (500.0, 500.0), (500.0, 500.0))  # < 0.1 s @60
    assert segment_episodes(frames, make_ctx()) == []


def test_gap_within_tolerance_is_bridged():
    frames: dict = {}
    add_linear_run(frames, 0, 10, (500.0, 500.0), (500.0, 500.0))
    add_linear_run(frames, 14, 16, (500.0, 500.0), (500.0, 500.0))  # gap of 4
    eps = segment_episodes(frames, make_ctx())
    assert len(eps) == 1
    assert eps[0].start_frame == 0 and eps[0].end_frame == 29
    assert len(eps[0].samples) == 26      # 10 + 16, gap frames not invented


def test_long_gap_splits_into_two_episodes():
    frames: dict = {}
    add_linear_run(frames, 0, 20, (500.0, 500.0), (500.0, 500.0))
    add_linear_run(frames, 100, 20, (500.0, 500.0), (500.0, 500.0))
    eps = segment_episodes(frames, make_ctx())
    assert len(eps) == 2
    assert eps[0].end_frame == 19 and eps[1].start_frame == 100


# ── Multi-enemy + association ────────────────────────────────────────────────


def test_two_simultaneous_enemies_stay_separate_tracks():
    frames: dict = {}
    add_linear_run(frames, 0, 30, (300.0, 540.0), (300.0, 540.0))
    add_linear_run(frames, 0, 30, (1600.0, 540.0), (1600.0, 540.0))
    eps = segment_episodes(frames, make_ctx())
    assert len(eps) == 2
    assert all(ep.multi_enemy for ep in eps)
    # No identity swap: each episode keeps a consistent side of the screen.
    for ep in eps:
        signs = {s.dx_hu > 0 for s in ep.samples}
        assert len(signs) == 1


def test_single_enemy_is_not_multi():
    frames: dict = {}
    add_linear_run(frames, 0, 30, (500.0, 500.0), (500.0, 500.0))
    eps = segment_episodes(frames, make_ctx())
    assert eps[0].multi_enemy is False
    assert eps[0].multi_from_frame is None


def test_multi_from_frame_marks_second_enemy_appearance():
    frames: dict = {}
    add_linear_run(frames, 0, 60, (300.0, 540.0), (300.0, 540.0))    # first enemy
    add_linear_run(frames, 40, 20, (1600.0, 540.0), (1600.0, 540.0))  # peeks later
    eps = segment_episodes(frames, make_ctx())
    first = next(ep for ep in eps if ep.start_frame == 0)
    second = next(ep for ep in eps if ep.start_frame == 40)
    # The long episode became a multi-fight only when the second head peeked.
    assert first.multi_enemy is True
    assert first.multi_from_frame == 40
    assert second.multi_from_frame == 40


def test_format_episodes_shows_when_multi_began():
    frames: dict = {}
    add_linear_run(frames, 0, 60, (300.0, 540.0), (300.0, 540.0))
    add_linear_run(frames, 40, 20, (1600.0, 540.0), (1600.0, 540.0))
    eps = segment_episodes(frames, make_ctx())
    text = format_episodes(eps, make_ctx())
    assert "multi=с 0.67" in text          # 40 / 60 fps — multi began here
    assert "multi=нет" not in text.split("\n")[1]  # first episode IS multi


# ── Distance buckets (head height as range proxy) ────────────────────────────


@pytest.mark.parametrize("height_px,bucket", [
    (40.0, "close"),    # 40/1080 ≈ 0.037
    (20.0, "mid"),      # ≈ 0.0185
    (10.0, "far"),      # ≈ 0.009
])
def test_distance_bucket_from_head_height(height_px, bucket):
    frames: dict = {}
    add_linear_run(frames, 0, 30, (500.0, 500.0), (500.0, 500.0), h=height_px)
    eps = segment_episodes(frames, make_ctx())
    assert eps[0].distance_bucket == bucket


# ── GT source (real CVAT track identity, no heuristics) ──────────────────────


def make_track_xml(tmp_path: Path) -> Path:
    xml = """<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <version>1.1</version>
  <track id="0" label="headshot" source="manual">
    <box frame="0" xtl="100" ytl="100" xbr="140" ybr="140" outside="0" occluded="0"/>
    <box frame="1" xtl="102" ytl="100" xbr="142" ybr="140" outside="0" occluded="0"/>
    <box frame="2" xtl="104" ytl="100" xbr="144" ybr="140" outside="1" occluded="0"/>
  </track>
  <track id="1" label="headshot" source="manual">
    <box frame="5" xtl="900" ytl="500" xbr="920" ybr="520" outside="0" occluded="0"/>
  </track>
</annotations>
"""
    path = tmp_path / "tracks.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_gt_tracks_parses_cvat_identity(tmp_path):
    tracks = gt_tracks(str(make_track_xml(tmp_path)))
    assert set(tracks.keys()) == {0, 1}
    assert [f for f, _ in tracks[0]] == [0, 1]       # outside=1 box skipped
    frame0_head = tracks[0][0][1]
    assert (frame0_head.cx, frame0_head.cy) == (120.0, 120.0)
    assert frame0_head.height_px == 40.0


# ── Human-checkable report (done-when: eye-check against the video) ──────────


def test_format_episodes_lists_each_episode_with_timestamps():
    frames: dict = {}
    add_linear_run(frames, 0, 40, (1500.0, 540.0), CENTRE)
    add_linear_run(frames, 40, 10, CENTRE, CENTRE)
    eps = segment_episodes(frames, make_ctx())
    text = format_episodes(eps, make_ctx())
    assert "1" in text                      # episode count
    assert "flick" in text
    assert "0.00" in text and "0.82" in text  # 0..49 @ 60fps in seconds
    assert "mid" in text


def test_format_episodes_handles_empty_list():
    text = format_episodes([], make_ctx())
    assert "0" in text


@pytest.mark.integration
def test_episodes_for_gt_real_clip():
    eps = episodes_for_gt(str(REAL_XML), make_ctx())
    assert len(eps) >= 1
    for ep in eps:
        assert 0 <= ep.start_frame <= ep.end_frame <= 659
        assert ep.kind in ("hold", "flick", "unengaged")
        assert ep.distance_bucket in ("close", "mid", "far")
        assert len(ep.samples) >= 1
    # Episodes are reported in chronological order.
    starts = [ep.start_frame for ep in eps]
    assert starts == sorted(starts)
