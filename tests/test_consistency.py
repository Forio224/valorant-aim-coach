"""Stage 3 tests: spread-first consistency axis — repeatability vs calibration.

Diagnosis logic (duel-scoped radial error):
  high spread                -> "repeatability" (inconsistent mechanics)
  low spread + high error    -> "calibration"  (consistent but aimed off)
  low spread + low error     -> "stable_accurate"
  too few duel frames        -> "insufficient" (hypothesis, not diagnosis)
"""

from pathlib import Path

import pytest

from aim_metrics import FrameSample
from engine.metrics.consistency import (
    ConsistencyReport,
    compute_consistency,
    format_consistency,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_XML = PROJECT_ROOT / "dataset1" / "clip2.xml"


def radial_samples(radials) -> list:
    """FrameSamples with given radial errors (dx carries it, dy=0)."""
    return [FrameSample(frame_idx=i, dx_hu=r, dy_hu=0.0, radial_hu=r,
                        head_height_px=20.0)
            for i, r in enumerate(radials)]


# ── Diagnosis classification ─────────────────────────────────────────────────


def test_high_spread_is_repeatability_problem():
    samples = radial_samples([0.2, 2.8] * 15)        # std ≈ 1.3 HU
    report = compute_consistency(samples)
    assert report.diagnosis == "repeatability"


def test_low_spread_high_error_is_calibration_problem():
    samples = radial_samples([1.5] * 30)             # std 0, MAE 1.5
    report = compute_consistency(samples)
    assert report.diagnosis == "calibration"


def test_low_spread_low_error_is_stable_accurate():
    samples = radial_samples([0.5] * 30)
    report = compute_consistency(samples)
    assert report.diagnosis == "stable_accurate"


def test_too_few_duel_frames_is_insufficient():
    samples = radial_samples([0.5] * 5)
    report = compute_consistency(samples)
    assert report.diagnosis == "insufficient"


def test_only_duel_frames_are_scored():
    # Radial 10 HU frames are outside the duel window and must not pollute.
    samples = radial_samples([0.5] * 30 + [10.0] * 30)
    report = compute_consistency(samples)
    assert report.diagnosis == "stable_accurate"
    assert report.duel_frames == 30


# ── Spread numbers ───────────────────────────────────────────────────────────


def test_spread_stats_computed_in_duel_scope():
    samples = radial_samples([1.0] * 30)
    report = compute_consistency(samples)
    assert report.duel_mae_hu == pytest.approx(1.0)
    assert report.std_hu == pytest.approx(0.0)
    assert report.iqr_hu == pytest.approx(0.0)
    assert report.p95_hu == pytest.approx(1.0)


# ── Report text ──────────────────────────────────────────────────────────────


def test_format_names_the_diagnosis():
    text = format_consistency(compute_consistency(radial_samples([1.5] * 30)))
    assert "калибровк" in text.lower()       # calibration named in Russian
    assert "std" in text or "разброс" in text.lower()


def test_format_marks_insufficient_data_as_hypothesis():
    text = format_consistency(compute_consistency(radial_samples([0.5] * 5)))
    assert "мало данных" in text.lower() or "гипотеза" in text.lower()


# ── Real clip ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_consistency_on_real_clip():
    from aim_metrics import iter_gt_samples
    samples = iter_gt_samples(str(REAL_XML), (960.0, 540.0))
    report = compute_consistency(samples)
    assert report.diagnosis in ("repeatability", "calibration",
                                "stable_accurate", "insufficient")
    assert report.duel_frames == 57          # known from the passport
    assert report.std_hu == pytest.approx(0.753, abs=0.01)
