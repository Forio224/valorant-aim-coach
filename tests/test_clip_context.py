"""Stage 0 tests: ClipContext data model + fps/metadata extraction.

Unit tests use synthetic CVAT XML (tmp_path); integration tests use the real
dataset1/clip2.* pair (fps=60.0, 660 frames, 1920x1080 — verified by hand).
"""

import math
from pathlib import Path

import pytest

from engine.clip_context import (
    ClipContext,
    CvatMeta,
    context_for_gt,
    context_for_video,
    parse_cvat_meta,
    read_video_meta,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_XML = PROJECT_ROOT / "dataset1" / "clip2.xml"
REAL_VIDEO = PROJECT_ROOT / "dataset1" / "clip2.mp4"


def make_cvat_xml(tmp_path: Path, size: int = 660, step: int = 1,
                  width: int = 1920, height: int = 1080) -> Path:
    """Synthetic CVAT XML with the same meta layout as dataset1/clip2.xml."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <version>1.1</version>
  <meta>
    <task>
      <size>{size}</size>
      <start_frame>0</start_frame>
      <stop_frame>{size - 1}</stop_frame>
      <frame_filter>step={step}</frame_filter>
      <original_size>
        <width>{width}</width>
        <height>{height}</height>
      </original_size>
      <source>clip_synthetic.mp4</source>
    </task>
  </meta>
</annotations>
"""
    path = tmp_path / "clip_synthetic.xml"
    path.write_text(xml, encoding="utf-8")
    return path


# ── ClipContext invariants ──────────────────────────────────────────────────


def test_crosshair_is_screen_centre():
    ctx = ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                      width=1920, height=1080, frame_count=660)
    assert ctx.crosshair == (960.0, 540.0)


def test_frame_to_seconds_uses_fps():
    ctx = ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                      width=1920, height=1080, frame_count=660)
    assert math.isclose(ctx.frame_to_seconds(47), 47 / 60.0)


def test_rejects_non_positive_fps():
    with pytest.raises(ValueError, match="fps"):
        ClipContext(player_id="p1", clip_id="c1", fps=0.0,
                    width=1920, height=1080, frame_count=660)


def test_rejects_empty_player_id():
    with pytest.raises(ValueError, match="player_id"):
        ClipContext(player_id="", clip_id="c1", fps=60.0,
                    width=1920, height=1080, frame_count=660)


def test_context_is_immutable():
    ctx = ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                      width=1920, height=1080, frame_count=660)
    with pytest.raises(Exception):
        ctx.fps = 30.0  # type: ignore[misc]


def test_optional_metadata_defaults_to_none():
    ctx = ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                      width=1920, height=1080, frame_count=660)
    assert ctx.sens is None and ctx.edpi is None
    assert ctx.agent is None and ctx.map_name is None


# ── CVAT meta parsing ───────────────────────────────────────────────────────


def test_parse_cvat_meta_reads_size_step_resolution(tmp_path):
    xml = make_cvat_xml(tmp_path, size=660, step=1, width=1920, height=1080)
    meta = parse_cvat_meta(str(xml))
    assert meta == CvatMeta(frame_count=660, step=1, width=1920, height=1080)


# ── GT path: fps source + validation ────────────────────────────────────────


def test_context_for_gt_uses_fps_override_without_video(tmp_path):
    xml = make_cvat_xml(tmp_path)
    ctx = context_for_gt(str(xml), video_path=None, fps_override=60.0,
                         player_id="p1")
    assert ctx.fps == 60.0
    assert ctx.frame_count == 660
    assert ctx.crosshair == (960.0, 540.0)
    assert ctx.clip_id == "clip_synthetic"  # defaults to xml stem


def test_context_for_gt_requires_some_fps_source(tmp_path):
    xml = make_cvat_xml(tmp_path)
    with pytest.raises(ValueError, match="fps"):
        context_for_gt(str(xml), video_path=None, fps_override=None,
                       player_id="p1")


def test_context_for_gt_rejects_non_unit_step(tmp_path):
    xml = make_cvat_xml(tmp_path, step=2)
    with pytest.raises(ValueError, match="step"):
        context_for_gt(str(xml), video_path=None, fps_override=60.0,
                       player_id="p1")


@pytest.mark.integration
def test_context_for_gt_rejects_frame_count_mismatch(tmp_path):
    # XML claims 9999 frames but the paired real video has 660 -> wrong pairing.
    xml = make_cvat_xml(tmp_path, size=9999)
    with pytest.raises(ValueError, match="frame"):
        context_for_gt(str(xml), video_path=str(REAL_VIDEO), player_id="p1")


@pytest.mark.integration
def test_context_for_gt_reads_fps_from_paired_video():
    ctx = context_for_gt(str(REAL_XML), video_path=str(REAL_VIDEO),
                         player_id="author")
    assert ctx.fps == 60.0
    assert ctx.frame_count == 660
    assert (ctx.width, ctx.height) == (1920, 1080)
    assert ctx.clip_id == "clip2"


# ── Video path ──────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_read_video_meta_real_clip():
    meta = read_video_meta(str(REAL_VIDEO))
    assert meta.fps == 60.0
    assert meta.frame_count == 660
    assert (meta.width, meta.height) == (1920, 1080)


@pytest.mark.integration
def test_context_for_video_real_clip():
    ctx = context_for_video(str(REAL_VIDEO), player_id="author")
    assert ctx.fps == 60.0
    assert ctx.crosshair == (960.0, 540.0)
    assert ctx.clip_id == "clip2"


def test_context_for_video_missing_file_raises():
    with pytest.raises(ValueError, match="open"):
        context_for_video("no_such_file.mp4", player_id="p1")
