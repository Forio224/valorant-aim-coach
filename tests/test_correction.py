"""Stage 4 tests: correction signature (overshoot/undershoot) on flick episodes.

PROXY caveat (amended roadmap): dx/dy are head-vs-fixed-crosshair, so a sign
flip can come from enemy strafe. Mitigations under test: flick-only episodes
where camera speed dominates, and a deadband on detector noise.
"""

from pathlib import Path

import pytest

from aim_metrics import FrameSample, Head
from engine.clip_context import ClipContext
from engine.episodes import Episode, episodes_for_gt, segment_episodes
from engine.metrics.correction import (
    CorrectionReport,
    compute_correction,
    format_correction,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRIEND_XML = PROJECT_ROOT / "dataset1" / "clip3.xml"
AUTHOR_XML = PROJECT_ROOT / "dataset1" / "output_clip.xml"

H = 20.0  # head height px; 1 HU = 20 px


def make_ctx(frame_count: int = 600) -> ClipContext:
    return ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                       width=1920, height=1080, frame_count=frame_count)


def episodes_from_hu_series(dx_series, dy_series=None):
    """One episode whose head follows the given HU offsets from the crosshair."""
    dy_series = dy_series or [0.0] * len(dx_series)
    frames = {
        i: [Head(cx=960.0 + dx * H, cy=540.0 + dy * H, height_px=H)]
        for i, (dx, dy) in enumerate(zip(dx_series, dy_series))
    }
    return segment_episodes(frames, make_ctx())


# ── X-axis verdicts ──────────────────────────────────────────────────────────


def test_clean_flick_has_no_overshoot():
    dx = [20 - i for i in range(21)] + [0.1] * 10        # monotone close-in
    report = compute_correction(episodes_from_hu_series(dx), make_ctx())
    assert report.flicks_analysed == 1
    assert report.verdicts[0].x == "clean"


def test_x_overshoot_detected_with_evidence_frame():
    dx = [20, 17, 14, 11, 8, 5, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 8
    report = compute_correction(episodes_from_hu_series(dx), make_ctx())
    v = report.verdicts[0]
    assert v.x == "overshoot"
    assert v.x_evidence_frame == 7           # first frame past zero beyond deadband
    assert report.x_overshoots == 1


def test_sign_flip_inside_deadband_is_clean():
    dx = [20, 17, 14, 11, 8, 5, 2, 0.5, -0.2, -0.25, 0.1] + [0.1] * 8
    report = compute_correction(episodes_from_hu_series(dx), make_ctx())
    assert report.verdicts[0].x == "clean"


def test_x_undershoot_stall_then_resume():
    dx = ([20, 17, 14, 11, 8, 5] + [5.0] * 6             # stopped short at 5 HU
          + [4, 3, 2, 1, 0.2] + [0.2] * 8)               # second correction wave
    report = compute_correction(episodes_from_hu_series(dx), make_ctx())
    v = report.verdicts[0]
    assert v.x == "undershoot"
    assert report.x_undershoots == 1


def _flick_frames(pairs, start: int = 100, kind: str = "flick",
                  speed: float = 50.0, track_id: int = 1) -> Episode:
    """Эпизод из (frame_offset, radial по X): кадры явные — для дырок (Фаза 4)."""
    samples = tuple(
        FrameSample(frame_idx=start + fo, dx_hu=r, dy_hu=0.0,
                    radial_hu=abs(r), head_height_px=H)
        for fo, r in pairs)
    return Episode(track_id=track_id, start_frame=start,
                   end_frame=start + pairs[-1][0], samples=samples,
                   kind=kind, distance_bucket="mid", multi_enemy=False,
                   multi_from_frame=None, duel_frames=0,
                   peak_closing_speed_hu_s=speed)


def test_sparse_flick_excluded_from_correction():
    holey = [(0, 3.0), (3, 1.0), (6, 0.6), (12, 0.3), (13, 0.3), (14, 0.3)]
    ep = _flick_frames(holey)
    rep = compute_correction([ep], make_ctx())
    assert rep.flicks_sparse == 1
    assert rep.flicks_analysed == 0


# ── Y axis + filtering ───────────────────────────────────────────────────────


def test_y_overshoot_detected_independently_of_x():
    dy = [15, 12, 9, 6, 3, 1, -0.8, -0.9, -0.4, 0.0] + [0.1] * 8
    dx = [0.0] * len(dy)
    report = compute_correction(episodes_from_hu_series(dx, dy), make_ctx())
    v = report.verdicts[0]
    assert v.y == "overshoot"
    assert v.x == "clean"


def test_hold_episodes_are_excluded():
    dx = [0.5] * 30                                       # born on target
    report = compute_correction(episodes_from_hu_series(dx), make_ctx())
    assert report.flicks_analysed == 0
    assert report.verdicts == ()


def test_slow_drift_flick_is_excluded_camera_not_dominant():
    # 20 HU over 380 frames ≈ 3 HU/s: too slow to attribute motion to the camera.
    n = 380
    dx = [20 * (1 - i / (n - 1)) for i in range(n)] + [0.1] * 10
    report = compute_correction(episodes_from_hu_series(dx),
                                make_ctx(frame_count=600))
    assert report.flicks_total == 1
    assert report.flicks_analysed == 0


# ── Report text ──────────────────────────────────────────────────────────────


def test_format_reports_counts_frames_and_proxy_caveat():
    dx = [20, 17, 14, 11, 8, 5, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 8
    report = compute_correction(episodes_from_hu_series(dx), make_ctx())
    text = format_correction(report, make_ctx())
    assert "перелёт" in text.lower()
    assert "кадр 7" in text                  # evidence anchor
    assert "прокси" in text.lower()          # honesty caveat is stated
    assert "гипотеза" in text.lower()        # 1 flick => hypothesis, not signature


def test_format_handles_no_flicks():
    text = format_correction(compute_correction([], make_ctx()), make_ctx())
    assert "0" in text


# ── Real clips (friend vs author — diff-test substrate) ─────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("xml", [FRIEND_XML, AUTHOR_XML])
def test_correction_runs_on_real_clip(xml):
    ctx = make_ctx(frame_count=700)
    eps = episodes_for_gt(str(xml), ctx)
    report = compute_correction(eps, ctx)
    assert report.flicks_analysed <= report.flicks_total <= len(eps)
    for v in report.verdicts:
        assert v.x in ("overshoot", "undershoot", "clean")
        assert v.y in ("overshoot", "undershoot", "clean")
