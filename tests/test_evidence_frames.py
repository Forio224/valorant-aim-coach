"""Stage B0 tests: schema 1.1 evidence geometry + annotated evidence frames.

Done-when: every evidence entry carries dx_hu/dy_hu/head_height_px, and
`render_evidence_frames` turns a report + video into annotated JPEGs whose
geometry (head box, crosshair, offset arrow) is reconstructed purely from the
report — no video resampling.
"""

import cv2
import numpy as np
import pytest

from aim_metrics import MIN_HEAD_PX, Head, sample_frame
from engine.clip_context import ClipContext
from engine.episodes import segment_episodes
from engine.evidence_frames import (collect_evidence_targets, head_box_px,
                                    render_evidence_frames)
from engine.report import SCHEMA_VERSION, build_report

W, H_SCREEN, FPS = 320, 240, 60.0
HEAD_H = 10.0


def make_ctx(frame_count=200) -> ClipContext:
    return ClipContext(player_id="p1", clip_id="c1", fps=FPS, width=W,
                       height=H_SCREEN, frame_count=frame_count)


def synthetic_clip():
    """Flick with an X overshoot at frame 6 + hold born 1 HU below-aim."""
    frames: dict = {}
    dx = [12, 10, 8, 6, 4, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 9
    for i, d in enumerate(dx):
        frames.setdefault(i, []).append(
            Head(W / 2 + d * HEAD_H, H_SCREEN / 2, height_px=HEAD_H))
    for i in range(100, 130):                     # hold, head 1 HU above aim
        frames.setdefault(i, []).append(
            Head(W / 2, H_SCREEN / 2 - HEAD_H, height_px=HEAD_H))
    ctx = make_ctx()
    episodes = segment_episodes(frames, ctx)
    samples = [s for ep in episodes for s in ep.samples]
    return ctx, samples, episodes


def synthetic_report():
    ctx, samples, episodes = synthetic_clip()
    return ctx, build_report(ctx, samples, episodes)


# ── HU -> px inversion ───────────────────────────────────────────────────────


def test_head_box_px_inverts_sample_frame():
    ctx = make_ctx()
    head = Head(cx=201.5, cy=77.25, height_px=24.0)
    s = sample_frame(7, head, ctx.crosshair)
    cx, cy, h = head_box_px(s.dx_hu, s.dy_hu, s.head_height_px,
                            ctx.width, ctx.height)
    assert cx == pytest.approx(head.cx, abs=1e-6)
    assert cy == pytest.approx(head.cy, abs=1e-6)
    assert h == pytest.approx(head.height_px)


def test_head_box_px_uses_the_same_tiny_head_guard_as_sample_frame():
    """Zero-height heads are normalised by MIN_HEAD_PX in sample_frame; the
    inversion must apply the identical guard or positions drift."""
    ctx = make_ctx()
    head = Head(cx=170.0, cy=110.0, height_px=0.0)
    s = sample_frame(0, head, ctx.crosshair)
    cx, cy, h = head_box_px(s.dx_hu, s.dy_hu, s.head_height_px,
                            ctx.width, ctx.height)
    assert cx == pytest.approx(head.cx, abs=1e-6)
    assert cy == pytest.approx(head.cy, abs=1e-6)
    assert h == pytest.approx(MIN_HEAD_PX)        # drawable box height


# ── Schema 1.1: every evidence entry carries geometry ────────────────────────


def test_schema_version_is_1_2():
    assert SCHEMA_VERSION == "1.2"


def test_every_evidence_entry_carries_geometry():
    _, report = synthetic_report()
    for finding in report["findings"]:
        for item in finding["evidence"]:
            for key in ("dx_hu", "dy_hu", "head_height_px"):
                assert key in item, f"{finding['metric']} evidence lacks {key}"
                assert isinstance(item[key], float)


def test_placement_evidence_geometry_matches_birth_sample():
    ctx, samples, episodes = synthetic_clip()
    report = build_report(ctx, samples, episodes)
    placement = next(f for f in report["findings"] if f["metric"] == "placement")
    births = {ep.start_frame: ep.samples[0] for ep in episodes}
    for item in placement["evidence"]:
        birth = births[item["frame"]]
        assert item["dx_hu"] == pytest.approx(birth.dx_hu, abs=1e-3)
        assert item["dy_hu"] == pytest.approx(birth.dy_hu, abs=1e-3)
        assert item["head_height_px"] == pytest.approx(birth.head_height_px)


def test_window_evidence_anchors_to_first_duel_frame():
    ctx, samples, episodes = synthetic_clip()
    report = build_report(ctx, samples, episodes)
    consistency = next(f for f in report["findings"]
                       if f["metric"] == "consistency")
    by_frame = {s.frame_idx: s for ep in episodes for s in ep.samples}
    for item in consistency["evidence"]:
        anchor = by_frame[item["frame_start"]]
        assert item["dx_hu"] == pytest.approx(anchor.dx_hu, abs=1e-3)
        assert item["head_height_px"] == pytest.approx(anchor.head_height_px)


# ── Target collection: dedupe, merge, cap ────────────────────────────────────


def test_collect_dedupes_frames_and_merges_notes():
    _, report = synthetic_report()
    targets = collect_evidence_targets(report)
    frames = [t.frame_idx for t in targets]
    assert frames == sorted(set(frames)), "duplicate frames must merge"
    # Frame 100 is both a placement verdict and a duel-window anchor.
    merged = next(t for t in targets if t.frame_idx == 100)
    assert len(merged.notes) >= 2
    assert "placement" in merged.metrics


def test_collect_caps_and_prefers_point_evidence_over_windows():
    _, report = synthetic_report()
    targets = collect_evidence_targets(report, cap=2)
    # Пре-айм-гейт отсеял рождение флика (12 HU): точечные улики — флипы
    # коррекции (кадры 6/7), а не оконные, что и проверяет приоритет.
    assert [t.frame_idx for t in targets] == [6, 7]


def test_collect_rejects_reports_without_geometry():
    _, report = synthetic_report()
    for finding in report["findings"]:
        for item in finding["evidence"]:
            item.pop("dx_hu", None)                   # simulate schema 1.0
    with pytest.raises(ValueError, match="1.1"):
        collect_evidence_targets(report)


# ── Rendering ────────────────────────────────────────────────────────────────


def _write_video(path, n_frames):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                             FPS, (W, H_SCREEN))
    assert writer.isOpened(), "cv2 cannot create the synthetic test video"
    for _ in range(n_frames):
        writer.write(np.full((H_SCREEN, W, 3), 128, dtype=np.uint8))
    writer.release()


def test_render_writes_one_annotated_jpeg_per_target(tmp_path):
    _, report = synthetic_report()
    video = tmp_path / "clip.mp4"
    _write_video(video, 130)
    out_dir = tmp_path / "evidence"

    paths = render_evidence_frames(str(video), report, str(out_dir))

    targets = collect_evidence_targets(report)
    assert len(paths) == len(targets)
    for path, target in zip(paths, targets):
        assert path.name == f"frame_{target.frame_idx:06d}.jpg"
        img = cv2.imread(str(path))
        assert img is not None and img.shape == (H_SCREEN, W, 3)
        # Annotation must have changed pixels of the flat-gray source frame.
        assert int(np.ptp(img)) > 30


def test_render_fails_fast_on_missing_video(tmp_path):
    _, report = synthetic_report()
    with pytest.raises(ValueError, match="видео|video"):
        render_evidence_frames(str(tmp_path / "nope.mp4"), report,
                               str(tmp_path / "out"))
