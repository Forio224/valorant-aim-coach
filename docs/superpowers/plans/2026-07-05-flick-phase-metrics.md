# Flick-Phase Metrics (Sub-phase 2A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the engine's `correction` finding with three phase-decomposition metrics — `flick_overshoot_hu`, `settle_time_frames`, `settle_jitter_hu` — computed from the `offset(t)` series already carried by `Episode.samples`.

**Architecture:** A new pure module `engine/metrics/flick_phase.py` splits each analysed flick episode at duel entry (the "near-band") into a ballistic approach and a settle window, then measures the overshoot amplitude, time-to-settle, and residual 2D jitter. `engine/report.py` adds the three aggregate (median) numbers into the existing `correction` finding's `values` dict — additive, no schema-version bump. Idea ported (not code) from the AGPL `Ngambarde/aim_trainer_analysis`; reimplemented from scratch.

**Tech Stack:** Python 3, stdlib `math`/`statistics`, frozen dataclasses, pytest. Runs via `.\.venv\Scripts\python.exe`.

## Global Constraints

- **Run Python only via** `.\.venv\Scripts\python.exe` (the `venv\` dir is broken; the correct one is `.venv\`). Tests: `.\.venv\Scripts\python.exe -m pytest -q`.
- **Numbers are computed ONLY by the engine** — this task adds engine numbers; nothing here is produced by the VLM.
- **Output-space proxy caveat is mandatory** on any human-facing text: dx/dy are the head vs the FIXED crosshair, so these are output-space signatures, not raw mouse mechanics; the phase boundary (duel entry) approximates "arrived at target".
- **Immutability:** all new data carriers are `@dataclass(frozen=True)`; never mutate inputs.
- **Schema stays `"1.1"`** — the enrichment is additive (extra keys inside an existing finding's `values`). Do NOT change `SCHEMA_VERSION`; do NOT touch coach/backend fixtures.
- **Phase boundary = duel entry:** the "near-band" defaults to `duel_hu` (`DEFAULT_DUEL_HU = 3.0`). Expose a `near_band_hu` override but default it to `duel_hu`.
- **Reuse existing gating:** only episodes with `ep.kind == "flick"` AND `ep.peak_closing_speed_hu_s >= MIN_FLICK_SPEED_HU_S` are analysed (identical to `compute_correction`).
- **Reuse existing constants** from `engine/metrics/correction.py`: `DEADBAND_HU` (0.3), `MIN_FLICK_SPEED_HU_S` (20.0), `SETTLE_S` (0.15). Do not re-declare them.

### Reference: existing types (do not redefine)

```python
# aim_metrics.py
@dataclass(frozen=True)
class FrameSample:
    frame_idx: int
    dx_hu: float          # + right of crosshair
    dy_hu: float          # - above crosshair (aim too low)
    radial_hu: float      # hypot(dx, dy) = absolute aim error this frame
    head_height_px: float

DEFAULT_DUEL_HU = 3.0

# engine/episodes.py  — Episode.samples IS the offset(t) series
@dataclass(frozen=True)
class Episode:
    track_id: int
    start_frame: int
    end_frame: int
    samples: Tuple[FrameSample, ...]
    kind: str                       # "hold" | "flick" | "unengaged"
    distance_bucket: str
    multi_enemy: bool
    multi_from_frame: Optional[int]
    duel_frames: int
    peak_closing_speed_hu_s: float

# engine/clip_context.py — constructed in tests as:
#   ClipContext(player_id="p1", clip_id="c1", fps=60.0, width=1920, height=1080, frame_count=600)
#   exposes ctx.fps and ctx.frame_to_seconds(frame_idx)
```

---

## File Structure

- **Create** `engine/metrics/flick_phase.py` — phase split + per-episode metrics + aggregate report + human-readable formatter. One responsibility: turn flick episodes into phase-decomposition numbers.
- **Create** `tests/test_flick_phase.py` — unit tests on synthetic HU series (mirrors `tests/test_correction.py` fixtures).
- **Modify** `engine/report.py` — import `compute_flick_phase`; add three keys to the `correction` finding's `values`.
- **Modify** `tests/test_report.py` — assert the three new keys appear on the correction finding.

---

## Task 1: Per-episode phase metrics

**Files:**
- Create: `engine/metrics/flick_phase.py`
- Test: `tests/test_flick_phase.py`

**Interfaces:**
- Consumes: `Episode`, `FrameSample`, `ClipContext`, `DEFAULT_DUEL_HU`; constants `DEADBAND_HU`, `MIN_FLICK_SPEED_HU_S`, `SETTLE_S` from `engine.metrics.correction`.
- Produces:
  - `FlickPhaseVerdict(episode_index:int, start_frame:int, time_s:float, overshoot_hu:float, settle_time_frames:int, settle_jitter_hu:float)` — frozen dataclass.
  - `_axis_overshoot(values: Sequence[float], deadband_hu: float) -> float`
  - `_entry_and_window(ep: Episode, near_band_hu: float, settle_frames: int) -> Optional[Tuple[int, List[FrameSample]]]`
  - `_stabilisation_index(window: Sequence[FrameSample]) -> Optional[int]`
  - `_jitter_hu(samples: Sequence[FrameSample]) -> float`
  - `_episode_metrics(ep: Episode, ctx: ClipContext, index: int, near_band_hu: float, settle_frames: int, deadband_hu: float) -> Optional[FlickPhaseVerdict]`
  - constant `SETTLE_STABLE_HU = 0.5`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_flick_phase.py`:

```python
"""Sub-phase 2A tests: flick-phase decomposition metrics.

PROXY caveat (inherited from correction): dx/dy are head-vs-fixed-crosshair, so
these are output-space signatures, not mouse mechanics. Fixtures mirror
tests/test_correction.py: one episode per synthetic HU series, 60 fps, 1 HU=20px.
"""

import pytest

from aim_metrics import Head
from engine.clip_context import ClipContext
from engine.episodes import segment_episodes
from engine.metrics.flick_phase import (
    FlickPhaseVerdict,
    _axis_overshoot,
    _episode_metrics,
)
from engine.metrics.correction import DEADBAND_HU

H = 20.0  # head height px; 1 HU = 20 px


def make_ctx(frame_count: int = 600) -> ClipContext:
    return ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                       width=1920, height=1080, frame_count=frame_count)


def one_episode(dx_series, dy_series=None):
    dy_series = dy_series or [0.0] * len(dx_series)
    frames = {
        i: [Head(cx=960.0 + dx * H, cy=540.0 + dy * H, height_px=H)]
        for i, (dx, dy) in enumerate(zip(dx_series, dy_series))
    }
    eps = segment_episodes(frames, make_ctx())
    assert len(eps) == 1, f"fixture expected 1 episode, got {len(eps)}"
    return eps[0]


# settle window at 60 fps = round(0.15*60) = 9 frames past duel entry.

def test_axis_overshoot_picks_opposite_side_peak():
    # initial sign +, crosses to -1.1 => opposite-side peak 1.1; -0.2 under deadband
    values = [20, 8, 2, -1.0, -1.1, -0.6, -0.2, 0.0]
    assert _axis_overshoot(values, DEADBAND_HU) == pytest.approx(1.1)


def test_axis_overshoot_zero_when_monotone():
    assert _axis_overshoot([20, 10, 3, 1, 0.1], DEADBAND_HU) == 0.0


def test_clean_flick_has_zero_overshoot_and_fast_settle():
    dx = [20 - i for i in range(21)] + [0.1] * 10   # duel entry at frame 17 (r=3)
    v = _episode_metrics(one_episode(dx), make_ctx(), 1,
                         near_band_hu=3.0, settle_frames=9, deadband_hu=DEADBAND_HU)
    assert v.overshoot_hu == 0.0
    assert v.settle_time_frames == 3          # entry 17 -> stabilised at frame 20
    assert v.settle_jitter_hu < 0.1


def test_overshoot_flick_measures_amplitude_and_settle():
    dx = [20, 17, 14, 11, 8, 5, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 8
    v = _episode_metrics(one_episode(dx), make_ctx(), 1,
                         near_band_hu=3.0, settle_frames=9, deadband_hu=DEADBAND_HU)
    assert v.overshoot_hu == pytest.approx(1.1)      # duel entry at frame 6
    assert v.settle_time_frames == 4                 # entry 6 -> stabilised frame 10
    assert v.settle_jitter_hu == pytest.approx(0.1106, abs=1e-3)


def test_oscillating_settle_never_stabilises_and_is_jittery():
    dx = [20, 15, 10, 5, 2, 1, -1, 1, -1, 1, -1, 1, -1]   # entry frame 4, |r|=1 forever
    v = _episode_metrics(one_episode(dx), make_ctx(), 1,
                         near_band_hu=3.0, settle_frames=9, deadband_hu=DEADBAND_HU)
    assert v.settle_time_frames == 8          # never within 0.5 HU -> full window (12-4)
    assert v.settle_jitter_hu > 0.8           # sustained +-1 HU swing


def test_returns_verdict_shape_with_indices():
    dx = [20 - i for i in range(21)] + [0.1] * 10
    v = _episode_metrics(one_episode(dx), make_ctx(), 7,
                         near_band_hu=3.0, settle_frames=9, deadband_hu=DEADBAND_HU)
    assert isinstance(v, FlickPhaseVerdict)
    assert v.episode_index == 7
    assert v.start_frame == 0
    assert v.time_s == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.metrics.flick_phase'`

- [ ] **Step 3: Write the module**

Create `engine/metrics/flick_phase.py`:

```python
"""Stage 2A: flick-phase decomposition — HOW the flick reached the head.

Enriches `correction` (the OUTCOME: did the crosshair overshoot?) with the
PROCESS. Each flick episode is split at duel entry (the "near-band") into a
ballistic approach and a settle window, all from the offset(t) series already
carried by Episode.samples — no new detection.

Metrics per flick:
  - overshoot_hu       peak excursion PAST the head (opposite side of approach)
  - settle_time_frames frames from duel entry until the crosshair stays within
                       SETTLE_STABLE_HU of the head
  - settle_jitter_hu   2D spread of the crosshair after it has landed

PROXY CAVEAT (inherited from correction): dx/dy are the head vs the FIXED
crosshair, so these are output-space signatures, NOT raw mouse mechanics; the
phase boundary (duel entry) approximates "arrived". Idea ported (not code) from
an AGPL project; reimplemented here.
"""

import math
import statistics
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from aim_metrics import DEFAULT_DUEL_HU, FrameSample
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.metrics.correction import (
    DEADBAND_HU,
    MIN_FLICK_SPEED_HU_S,
    SETTLE_S,
)

SETTLE_STABLE_HU = 0.5   # radial at/below this = "landed"; used to time the settle


@dataclass(frozen=True)
class FlickPhaseVerdict:
    """Per-flick phase numbers, frame-anchored for evidence."""
    episode_index: int          # 1-based, matches format_episodes numbering
    start_frame: int
    time_s: float
    overshoot_hu: float
    settle_time_frames: int
    settle_jitter_hu: float


@dataclass(frozen=True)
class FlickPhaseReport:
    flicks_analysed: int
    median_overshoot_hu: float
    median_settle_time_frames: float
    median_settle_jitter_hu: float
    verdicts: Tuple[FlickPhaseVerdict, ...]


# ── Per-episode primitives ───────────────────────────────────────────────────

def _axis_overshoot(values: Sequence[float], deadband_hu: float) -> float:
    """Peak excursion to the side OPPOSITE the initial approach (0 if none).

    Initial side = sign of the first value beyond the deadband. Any later value
    beyond the deadband on the opposite side contributes its magnitude.
    """
    first = next((v for v in values if abs(v) >= deadband_hu), None)
    if first is None:
        return 0.0
    initial_positive = first > 0
    opposite = [abs(v) for v in values
                if abs(v) >= deadband_hu and (v > 0) != initial_positive]
    return max(opposite, default=0.0)


def _entry_and_window(ep: Episode, near_band_hu: float,
                      settle_frames: int,
                      ) -> Optional[Tuple[int, List[FrameSample]]]:
    """Duel entry frame + the settle window [entry, entry+settle_frames]."""
    entry = next((s.frame_idx for s in ep.samples
                  if s.radial_hu <= near_band_hu), None)
    if entry is None:
        return None
    window = [s for s in ep.samples
              if entry <= s.frame_idx <= entry + settle_frames]
    return entry, window


def _stabilisation_index(window: Sequence[FrameSample]) -> Optional[int]:
    """First window index from which radial stays <= SETTLE_STABLE_HU to the end."""
    for idx in range(len(window)):
        if all(s.radial_hu <= SETTLE_STABLE_HU for s in window[idx:]):
            return idx
    return None


def _jitter_hu(samples: Sequence[FrameSample]) -> float:
    """2D crosshair spread over the given samples (population stdev per axis)."""
    if len(samples) < 2:
        return 0.0
    return math.hypot(statistics.pstdev(s.dx_hu for s in samples),
                      statistics.pstdev(s.dy_hu for s in samples))


def _episode_metrics(ep: Episode, ctx: ClipContext, index: int,
                     near_band_hu: float, settle_frames: int,
                     deadband_hu: float) -> Optional[FlickPhaseVerdict]:
    ew = _entry_and_window(ep, near_band_hu, settle_frames)
    if ew is None:
        return None
    entry, window = ew
    overshoot = math.hypot(
        _axis_overshoot([s.dx_hu for s in window], deadband_hu),
        _axis_overshoot([s.dy_hu for s in window], deadband_hu),
    )
    stab = _stabilisation_index(window)
    if stab is None:
        settle_time = window[-1].frame_idx - entry
        tail = window
    else:
        settle_time = window[stab].frame_idx - entry
        tail = window[stab:]
    return FlickPhaseVerdict(
        episode_index=index,
        start_frame=ep.start_frame,
        time_s=ctx.frame_to_seconds(ep.start_frame),
        overshoot_hu=overshoot,
        settle_time_frames=settle_time,
        settle_jitter_hu=_jitter_hu(tail),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/metrics/flick_phase.py tests/test_flick_phase.py
git commit -m "feat(engine): per-episode flick-phase metrics (overshoot/settle/jitter)"
```

---

## Task 2: Aggregate `compute_flick_phase` + gating + formatter

**Files:**
- Modify: `engine/metrics/flick_phase.py`
- Test: `tests/test_flick_phase.py`

**Interfaces:**
- Consumes: everything from Task 1.
- Produces:
  - `compute_flick_phase(episodes: Sequence[Episode], ctx: ClipContext, duel_hu: float = DEFAULT_DUEL_HU, near_band_hu: Optional[float] = None, deadband_hu: float = DEADBAND_HU, min_flick_speed_hu_s: float = MIN_FLICK_SPEED_HU_S) -> FlickPhaseReport`
  - `format_flick_phase(report: FlickPhaseReport, ctx: ClipContext) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_flick_phase.py`:

```python
from engine.episodes import episodes_for_gt
from engine.metrics.flick_phase import compute_flick_phase, format_flick_phase
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRIEND_XML = PROJECT_ROOT / "dataset1" / "clip3.xml"


def episodes_for_series(dx_series, dy_series=None):
    dy_series = dy_series or [0.0] * len(dx_series)
    frames = {
        i: [Head(cx=960.0 + dx * H, cy=540.0 + dy * H, height_px=H)]
        for i, (dx, dy) in enumerate(zip(dx_series, dy_series))
    }
    return segment_episodes(frames, make_ctx())


def test_hold_episode_is_not_analysed():
    eps = episodes_for_series([0.5] * 30)          # born on target => "hold"
    report = compute_flick_phase(eps, make_ctx())
    assert report.flicks_analysed == 0
    assert report.verdicts == ()
    assert report.median_overshoot_hu == 0.0


def test_slow_drift_flick_excluded_camera_not_dominant():
    n = 380                                        # ~3 HU/s: too slow for camera
    dx = [20 * (1 - i / (n - 1)) for i in range(n)] + [0.1] * 10
    report = compute_flick_phase(episodes_for_series(dx), make_ctx(frame_count=600))
    assert report.flicks_analysed == 0


def test_medians_over_two_flicks():
    clean = [20 - i for i in range(21)] + [0.1] * 10          # overshoot 0.0
    over = [20, 17, 14, 11, 8, 5, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 8  # 1.1
    eps = episodes_for_series(clean) + episodes_for_series(over)
    report = compute_flick_phase(eps, make_ctx())
    assert report.flicks_analysed == 2
    assert report.median_overshoot_hu == pytest.approx(0.55)   # median(0.0, 1.1)


def test_empty_input_is_all_zeros():
    report = compute_flick_phase([], make_ctx())
    assert report.flicks_analysed == 0
    assert report.median_settle_time_frames == 0.0
    assert report.median_settle_jitter_hu == 0.0
    assert report.verdicts == ()


def test_near_band_override_changes_entry():
    # tighter near-band delays duel entry, so the settle window shifts.
    dx = [20 - i for i in range(21)] + [0.1] * 10
    loose = compute_flick_phase(episodes_for_series(dx), make_ctx(), near_band_hu=3.0)
    tight = compute_flick_phase(episodes_for_series(dx), make_ctx(), near_band_hu=1.0)
    assert loose.verdicts[0].settle_time_frames != tight.verdicts[0].settle_time_frames


def test_format_states_proxy_caveat():
    dx = [20, 17, 14, 11, 8, 5, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 8
    report = compute_flick_phase(episodes_for_series(dx), make_ctx())
    text = format_flick_phase(report, make_ctx())
    assert "прокси" in text.lower()
    assert "перелёт" in text.lower() or "overshoot" in text.lower()


def test_format_handles_empty():
    text = format_flick_phase(compute_flick_phase([], make_ctx()), make_ctx())
    assert "0" in text


@pytest.mark.integration
def test_runs_on_real_clip():
    ctx = make_ctx(frame_count=700)
    eps = episodes_for_gt(str(FRIEND_XML), ctx)
    report = compute_flick_phase(eps, ctx)
    assert report.flicks_analysed <= len(eps)
    for v in report.verdicts:
        assert v.overshoot_hu >= 0.0
        assert v.settle_time_frames >= 0
        assert v.settle_jitter_hu >= 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_flick_phase'`

- [ ] **Step 3: Add the aggregate + formatter**

Append to `engine/metrics/flick_phase.py`:

```python
# ── Episode-set analysis ─────────────────────────────────────────────────────

def compute_flick_phase(episodes: Sequence[Episode], ctx: ClipContext,
                        duel_hu: float = DEFAULT_DUEL_HU,
                        near_band_hu: Optional[float] = None,
                        deadband_hu: float = DEADBAND_HU,
                        min_flick_speed_hu_s: float = MIN_FLICK_SPEED_HU_S,
                        ) -> FlickPhaseReport:
    """Phase metrics over the camera-dominant flick episodes (same gate as
    compute_correction). near_band_hu defaults to the duel threshold."""
    band = duel_hu if near_band_hu is None else near_band_hu
    settle_frames = max(int(round(SETTLE_S * ctx.fps)), 1)

    verdicts: List[FlickPhaseVerdict] = []
    for i, ep in enumerate(episodes, start=1):
        if ep.kind != "flick" or ep.peak_closing_speed_hu_s < min_flick_speed_hu_s:
            continue
        v = _episode_metrics(ep, ctx, i, band, settle_frames, deadband_hu)
        if v is not None:
            verdicts.append(v)

    if not verdicts:
        return FlickPhaseReport(0, 0.0, 0.0, 0.0, ())
    return FlickPhaseReport(
        flicks_analysed=len(verdicts),
        median_overshoot_hu=statistics.median(v.overshoot_hu for v in verdicts),
        median_settle_time_frames=statistics.median(
            v.settle_time_frames for v in verdicts),
        median_settle_jitter_hu=statistics.median(
            v.settle_jitter_hu for v in verdicts),
        verdicts=tuple(verdicts),
    )


# ── Human-readable report ────────────────────────────────────────────────────

def format_flick_phase(report: FlickPhaseReport, ctx: ClipContext) -> str:
    lines = [
        "=== ФАЗЫ ФЛИКА (баллистика -> доводка) ===",
        f"  Проанализировано фликов: {report.flicks_analysed}",
        f"  Медиана перелёта: {report.median_overshoot_hu:.2f} HU",
        f"  Медиана времени доводки: {report.median_settle_time_frames:.1f} кадр.",
        f"  Медиана джиттера доводки: {report.median_settle_jitter_hu:.2f} HU",
    ]
    for v in report.verdicts:
        lines.append(
            f"  #{v.episode_index:<2} старт кадр {v.start_frame} ({v.time_s:.2f} c):"
            f"  перелёт {v.overshoot_hu:.2f} HU,"
            f"  доводка {v.settle_time_frames} кадр.,"
            f"  джиттер {v.settle_jitter_hu:.2f} HU"
        )
    lines.append("  Замечание: фазы считаны по output-space (прицел↔голова) —"
                 " ПРОКСИ, не механика мыши; граница фаз = вход в дуэль.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py -q`
Expected: PASS (all flick-phase tests, integration marker runs the real clip)

- [ ] **Step 5: Commit**

```bash
git add engine/metrics/flick_phase.py tests/test_flick_phase.py
git commit -m "feat(engine): aggregate compute_flick_phase + formatter"
```

---

## Task 3: Wire phase metrics into the `correction` finding

**Files:**
- Modify: `engine/report.py:167-205` (`_correction_finding`) and its imports (`engine/report.py:16-26`)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `compute_flick_phase` from `engine.metrics.flick_phase`.
- Produces: the `correction` finding's `values` dict gains three keys — `flick_overshoot_hu`, `settle_time_frames`, `settle_jitter_hu` (rounded floats, or `None` when NaN — impossible here, but `_r` guards it).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report.py` (reuse whatever `build_report` fixture the file already sets up; the snippet below builds its own to be self-contained):

```python
def test_correction_finding_carries_flick_phase_values():
    from aim_metrics import Head
    from engine.clip_context import ClipContext
    from engine.episodes import segment_episodes
    from engine.report import build_report

    H = 20.0
    ctx = ClipContext(player_id="p1", clip_id="c1", fps=60.0,
                      width=1920, height=1080, frame_count=600)
    dx = [20, 17, 14, 11, 8, 5, 2, -1.0, -1.1, -0.6, -0.2, 0.0] + [0.1] * 8
    frames = {i: [Head(cx=960.0 + v * H, cy=540.0, height_px=H)]
              for i, v in enumerate(dx)}
    episodes = segment_episodes(frames, ctx)
    samples = [s for ep in episodes for s in ep.samples]

    report = build_report(ctx, samples, episodes)
    correction = next(f for f in report["findings"] if f["metric"] == "correction")

    assert "flick_overshoot_hu" in correction["values"]
    assert "settle_time_frames" in correction["values"]
    assert "settle_jitter_hu" in correction["values"]
    assert correction["values"]["flick_overshoot_hu"] == pytest.approx(1.1)
```

If `pytest` is not already imported at the top of `tests/test_report.py`, add `import pytest`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_report.py::test_correction_finding_carries_flick_phase_values -q`
Expected: FAIL — `KeyError: 'flick_overshoot_hu'`

- [ ] **Step 3: Add the import**

In `engine/report.py`, in the imports block (around line 20, next to the other metric imports), add:

```python
from engine.metrics.flick_phase import compute_flick_phase
```

- [ ] **Step 4: Enrich the correction finding's values**

In `engine/report.py`, inside `_correction_finding`, immediately after the line `rep = compute_correction(episodes, ctx, duel_hu=duel_hu)`, add:

```python
    fp = compute_flick_phase(episodes, ctx, duel_hu=duel_hu)
```

Then in the same function's returned dict, replace the `"values"` block:

```python
        "values": {"flicks_total": rep.flicks_total,
                   "flicks_analysed": rep.flicks_analysed,
                   "x_overshoots": rep.x_overshoots,
                   "x_undershoots": rep.x_undershoots,
                   "y_overshoots": rep.y_overshoots,
                   "y_undershoots": rep.y_undershoots},
```

with:

```python
        "values": {"flicks_total": rep.flicks_total,
                   "flicks_analysed": rep.flicks_analysed,
                   "x_overshoots": rep.x_overshoots,
                   "x_undershoots": rep.x_undershoots,
                   "y_overshoots": rep.y_overshoots,
                   "y_undershoots": rep.y_undershoots,
                   "flick_overshoot_hu": _r(fp.median_overshoot_hu),
                   "settle_time_frames": _r(fp.median_settle_time_frames, 1),
                   "settle_jitter_hu": _r(fp.median_settle_jitter_hu)},
```

(`_r` already exists in `engine/report.py` and turns NaN into `None` for a valid JSON contract.)

- [ ] **Step 5: Run the new test + the full report + engine suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_report.py tests/test_flick_phase.py tests/test_correction.py tests/test_evidence_frames.py -q`
Expected: PASS — including `test_schema_version_is_1_1` (unchanged) and the new value-keys test.

- [ ] **Step 6: Run the whole suite (no regressions in coach/backend)**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS — coach/backend fixtures still pin `schema_version == "1.1"`; the enrichment is additive, so nothing downstream breaks.

- [ ] **Step 7: Commit**

```bash
git add engine/report.py tests/test_report.py
git commit -m "feat(report): surface flick-phase medians on the correction finding"
```

---

## Self-Review

**1. Spec coverage** (against sub-phase 2A in `2026-07-05-phase2-progress-loop-design.md`, Компонент A):
- `flick_overshoot_hu` — Task 1 `_axis_overshoot` + `_episode_metrics`; surfaced Task 3. ✓
- `settle_time_frames` — Task 1 `_stabilisation_index` + `_episode_metrics`; surfaced Task 3. ✓
- `settle_jitter_hu` — Task 1 `_jitter_hu`; triggers Phase-2 tracking supplementary later (out of 2A scope, noted). ✓
- Phase boundary = duel entry / `near_band_hu` knob — Task 1 `_entry_and_window`, override tested Task 2. ✓
- Reuse existing offset(t) with no new detector — uses `Episode.samples`. ✓
- Output-space proxy caveat — in module docstring + `format_flick_phase`. ✓
- `MIN_*` confidence: the correction finding keeps its existing `_confidence(rep.flicks_analysed, MIN_FLICKS_FOR_DIAGNOSIS)`; flick-phase reuses the identical gate, so counts match — no separate confidence needed. ✓
- 2A is self-contained (no Steam ID, no external API) — confirmed; only engine + its tests touched. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows full code; every test step shows full assertions with computed expected values. ✓

**3. Type consistency:** `compute_flick_phase` → `FlickPhaseReport` with fields `median_overshoot_hu`/`median_settle_time_frames`/`median_settle_jitter_hu`; report maps them to `flick_overshoot_hu`/`settle_time_frames`/`settle_jitter_hu` (deliberate rename at the contract boundary, applied consistently in Task 3 and asserted in its test). `_episode_metrics` signature identical across Task 1 definition, Task 1 tests, and Task 2 aggregate call. `near_band_hu` defaults to `None`→`duel_hu` everywhere. ✓

---

## Notes for the implementer

- `settle_frames = round(0.15 * 60) = 9` at 60 fps. All hand-computed expected values in the tests assume 60 fps (`make_ctx`).
- The `overshoot` in `_axis_overshoot` returns a magnitude (always ≥ 0); the sign/direction stays with the existing `correction` per-axis verdicts. The two are complementary, not duplicative.
- CLI wiring (printing `format_flick_phase` from `aim_metrics.py`) is intentionally out of scope for 2A — the report enrichment is what feeds the product and the Phase-2 loop. Add it later only if the offline CLI needs it.
