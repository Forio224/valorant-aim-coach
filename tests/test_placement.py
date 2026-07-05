"""Stage 2 tests: crosshair placement at track birth (pre-aim, metric #1).

Sign convention (aim_metrics): image y points DOWN, dy_hu = (head_cy - cross_y)/h.
dy < 0  => head ABOVE the crosshair => crosshair BELOW the head line (lazy aim).
"""

from pathlib import Path

import pytest

from aim_metrics import Head
from engine.clip_context import ClipContext
from engine.episodes import episodes_for_gt, segment_episodes
from engine.metrics.placement import (
    PlacementReport,
    compute_placement,
    format_placement,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_XML = PROJECT_ROOT / "dataset1" / "clip2.xml"


def make_ctx() -> ClipContext:
    return ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                       width=1920, height=1080, frame_count=600)


def episodes_with_birth_heads(*heads: Head, n_frames: int = 30):
    """Each head spawns its own static episode starting at frame 0."""
    frames: dict = {}
    for head in heads:
        for i in range(n_frames):
            frames.setdefault(i, []).append(head)
    return segment_episodes(frames, make_ctx())


# ── Vertical verdicts at birth ───────────────────────────────────────────────


def test_crosshair_below_head_line_detected():
    # Head appears 3 HU ABOVE the crosshair => aim was below the head line.
    eps = episodes_with_birth_heads(Head(cx=960.0, cy=480.0, height_px=20.0))
    report = compute_placement(eps, make_ctx())
    assert report.n_below == 1 and report.n_above == 0 and report.n_on_line == 0
    assert report.verdicts[0].vertical == "below"
    assert report.verdicts[0].dy_hu == pytest.approx(-3.0)


def test_crosshair_above_head_line_detected():
    eps = episodes_with_birth_heads(Head(cx=960.0, cy=600.0, height_px=20.0))
    report = compute_placement(eps, make_ctx())
    assert report.n_above == 1
    assert report.verdicts[0].vertical == "above"


def test_on_line_within_band():
    eps = episodes_with_birth_heads(Head(cx=965.0, cy=542.0, height_px=20.0))
    report = compute_placement(eps, make_ctx())
    assert report.n_on_line == 1
    assert report.verdicts[0].vertical == "on_line"


def test_band_threshold_respected():
    # dy = -0.4 HU: below the line but inside the default 0.5 HU band.
    eps = episodes_with_birth_heads(Head(cx=960.0, cy=532.0, height_px=20.0))
    report = compute_placement(eps, make_ctx())
    assert report.verdicts[0].vertical == "on_line"
    # With a tighter band the same episode counts as "below".
    tight = compute_placement(eps, make_ctx(), band_hu=0.3)
    assert tight.verdicts[0].vertical == "below"


# ── Aggregates + evidence anchors ────────────────────────────────────────────


def test_report_aggregates_over_episodes():
    eps = episodes_with_birth_heads(
        Head(cx=960.0, cy=480.0, height_px=20.0),   # below
        Head(cx=300.0, cy=440.0, height_px=20.0),   # below (and far left)
        Head(cx=960.0, cy=545.0, height_px=20.0),   # on line
    )
    report = compute_placement(eps, make_ctx())
    assert report.total_episodes == 3
    assert report.n_below == 2
    assert report.mean_dy_hu < 0
    # Every verdict is anchored to the birth frame of its episode.
    assert all(v.frame_idx == 0 for v in report.verdicts)


def test_verdicts_carry_episode_kind_and_time():
    eps = episodes_with_birth_heads(Head(cx=960.0, cy=480.0, height_px=20.0))
    report = compute_placement(eps, make_ctx())
    v = report.verdicts[0]
    assert v.kind in ("hold", "flick", "unengaged")
    assert v.time_s == pytest.approx(0.0)


# ── Human-readable report (done-when: "N из M ниже головы на >=X HU") ────────


def test_format_states_n_of_m_below_with_frames():
    eps = episodes_with_birth_heads(
        Head(cx=960.0, cy=480.0, height_px=20.0),   # below
        Head(cx=960.0, cy=545.0, height_px=20.0),   # on line
    )
    text = format_placement(compute_placement(eps, make_ctx()), make_ctx())
    assert "1 из 2" in text
    assert "ниже" in text
    assert "кадр 0" in text          # evidence anchor
    assert "0.5" in text             # the X HU band is stated


def test_format_handles_no_episodes():
    text = format_placement(compute_placement([], make_ctx()), make_ctx())
    assert "0" in text


# ── Real clip ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_placement_on_real_clip():
    ctx = make_ctx()
    eps = episodes_for_gt(str(REAL_XML), ctx)
    report = compute_placement(eps, ctx)
    assert report.total_episodes == len(eps)
    assert report.n_below + report.n_above + report.n_on_line == len(eps)
    birth_frames = {ep.start_frame for ep in eps}
    assert {v.frame_idx for v in report.verdicts} == birth_frames
