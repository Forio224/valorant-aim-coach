# -*- coding: utf-8 -*-
"""Тесты общих помощников провайдеров: нумерация, ресайз, кап, подписи."""
import base64
import io
from pathlib import Path

from coach.providers import common

FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_frame_number_parses_padded_name():
    assert common.frame_number(Path("frame_000177.jpg")) == 177
    assert common.frame_number(Path("noNumberHere")) is None


def test_frame_numbers_skips_unnumbered():
    paths = [Path("frame_000010.jpg"), Path("banner.jpg"), Path("frame_000020.jpg")]
    assert common.frame_numbers(paths) == [10, 20]


def test_frame_label_uses_number_or_name():
    assert common.frame_label(Path("frame_000177.jpg")) == "Кадр-улика 177"
    assert common.frame_label(Path("weird.jpg")) == "Кадр-улика weird.jpg"


def test_capped_frames_limits_to_max():
    paths = [Path(f"frame_{n:06d}.jpg") for n in range(20)]
    assert len(common.capped_frames(paths, 10)) == 10
    assert common.capped_frames(paths, 10) == paths[:10]


def test_encode_frame_small_is_byte_identical(tmp_path):
    p = tmp_path / "frame_000001.jpg"
    p.write_bytes(FAKE_JPEG)
    assert base64.b64decode(common.encode_frame(p)) == FAKE_JPEG


def test_encode_frame_shrinks_wide(tmp_path):
    from PIL import Image

    p = tmp_path / "frame_000001.jpg"
    Image.new("RGB", (2000, 1120), (30, 40, 50)).save(p, format="JPEG")
    decoded = Image.open(io.BytesIO(base64.b64decode(common.encode_frame(p))))
    assert decoded.width == common.COACH_IMAGE_MAX_WIDTH
    assert decoded.height == 573  # round(1120 * 1024/2000)


def test_constants():
    assert common.COACH_IMAGE_MAX_WIDTH == 1024
    assert common.COACH_IMAGE_JPEG_QUALITY == 85
    assert common.MAX_IMAGES == 10
