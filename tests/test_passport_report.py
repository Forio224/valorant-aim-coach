"""Stage 0 done-when: the passport report carries ClipContext metadata."""

from aim_metrics import Head, compute_passport, format_passport, sample_frame
from engine.clip_context import ClipContext


def make_ctx(**overrides):
    base = dict(player_id="author", clip_id="clip2", fps=60.0,
                width=1920, height=1080, frame_count=660)
    base.update(overrides)
    return ClipContext(**base)


def make_passport():
    samples = [sample_frame(0, Head(cx=1000.0, cy=500.0, height_px=20.0),
                            (960.0, 540.0))]
    return compute_passport(samples)


def test_report_includes_player_clip_and_fps():
    text = format_passport(make_passport(), label="gt: clip2.xml",
                           ctx=make_ctx())
    assert "author" in text
    assert "clip2" in text
    assert "60" in text          # fps
    assert "1920" in text and "1080" in text


def test_report_includes_optional_metadata_when_given():
    ctx = make_ctx(sens=0.4, edpi=320.0, agent="Jett", map_name="Ascent")
    text = format_passport(make_passport(), label="gt: clip2.xml", ctx=ctx)
    assert "0.4" in text and "320" in text
    assert "Jett" in text and "Ascent" in text


def test_report_omits_optional_metadata_when_absent():
    text = format_passport(make_passport(), label="gt: clip2.xml",
                           ctx=make_ctx())
    assert "Jett" not in text and "Ascent" not in text
    assert "None" not in text    # no fabricated/placeholder values
