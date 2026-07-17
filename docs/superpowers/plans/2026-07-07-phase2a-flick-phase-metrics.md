# Фаза 2A: фаз-метрики флика Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Обогатить движок фаз-метриками флика (перелёт / скорость доводки / рывковость / путь доводки), не трогая каталог, валидатор, промпт и фронт.

**Architecture:** Новый модуль `engine/metrics/flick_phase.py` режет каждый флик-эпизод по ряду `offset(t)=radial_hu` на баллистику (старт → вход в near-band) и settle (вход → стабилизация), считает четыре метрики движком и агрегирует медианой с честным `phase_confidence`. `engine/report.py` доклеивает агрегаты в `values` существующего `correction`-finding'а, НЕ трогая старые ключи. CLI печатает разложение рядом с `correction`.

**Tech Stack:** Python 3, dataclasses, `statistics` (median/pstdev), pytest. Без новых зависимостей.

## Global Constraints

- Python только через `.\.venv\Scripts\python.exe` (каталог `venv\` сломан).
- Тесты: `.\.venv\Scripts\python.exe -m pytest -q`.
- Управляющий принцип: любые числа в отчёте происходят из движка; VLM их не производит. Эта фаза только добавляет числа движка.
- **Область только `engine/` (+ CLI-печать).** НЕ трогать каталог, валидатор, промпт, выбор дрилла, `build_criterion`, фронтенд, петлю прогресса.
- Старые ключи `correction.values` (`flicks_total`, `flicks_analysed`, `x_overshoots`, `x_undershoots`, `y_overshoots`, `y_undershoots`) НЕ удалять и НЕ переименовывать — от них зависит `build_criterion("correction")` Фазы 1.
- Тот же набор флик-эпизодов, что у `correction`: `ep.kind == "flick"` И `ep.peak_closing_speed_hu_s >= MIN_FLICK_SPEED_HU_S`.
- Флик, который «не дошёл» (нет входа в near-band) или «не оселся» (нет стабильного прогона), из агрегатов ИСКЛЮЧАЕТСЯ — чисел не выдумываем.
- Метрики: `flick_overshoot_hu` = истинный перелёт через центр по знаковым осям (не радиальный отскок); `settle_jitter_hu` = `stdev(Δradial)` (по производной); `settle_time` хранить и в кадрах, и в мс; `correction_path_hu` = `Σ|Δradial|`.
- Дефолты ручек (калибруемы): `NEAR_BAND_HU=0.8`, `SETTLE_TOL_HU=0.35`, `SETTLE_STABLE_FRAMES=3`, `MIN_FLICKS_FOR_PHASE=3`. Deadband знака наследуется из `correction` (`DEADBAND_HU=0.3`).
- Язык кода/комментариев — как в окружающих файлах (русскоязычные докстроки, английские идентификаторы).
- Спека: `docs/superpowers/specs/2026-07-07-phase2a-flick-phase-metrics-design.md`.

---

### Task 1: Модуль фаз-метрик `engine/metrics/flick_phase.py`

**Files:**
- Create: `engine/metrics/flick_phase.py`
- Test: `tests/test_flick_phase.py`

**Interfaces:**
- Consumes: `engine.episodes.Episode` (`kind`, `peak_closing_speed_hu_s`, `start_frame`, `samples` — кортеж `aim_metrics.FrameSample{frame_idx, dx_hu, dy_hu, radial_hu, head_height_px}`); `engine.clip_context.ClipContext` (`fps`, `frame_to_seconds`); `engine.metrics.correction.DEADBAND_HU`, `MIN_FLICK_SPEED_HU_S`.
- Produces:
  - `@dataclass(frozen=True) FlickPhase{episode_index:int, start_frame:int, arrived:bool, settled:bool, flick_overshoot_hu:Optional[float], settle_time_frames:Optional[int], settle_jitter_hu:Optional[float], correction_path_hu:Optional[float], overshoot_evidence_frame:Optional[int]}`.
  - `@dataclass(frozen=True) FlickPhaseReport{flicks_analysed:int, flicks_arrived:int, flicks_settled:int, flick_overshoot_hu_median:Optional[float], settle_time_frames_median:Optional[float], settle_jitter_hu_median:Optional[float], correction_path_hu_median:Optional[float], phase_confidence:str, phases:Tuple[FlickPhase,...]}`.
  - `compute_flick_phases(episodes, ctx, near_band_hu=NEAR_BAND_HU, settle_tol_hu=SETTLE_TOL_HU, stable_frames=SETTLE_STABLE_FRAMES, deadband_hu=DEADBAND_HU, min_flick_speed_hu_s=MIN_FLICK_SPEED_HU_S) -> FlickPhaseReport`.
  - `format_flick_phases(report: FlickPhaseReport, ctx: ClipContext) -> str`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_flick_phase.py`:

```python
# -*- coding: utf-8 -*-
"""Тесты фаз-метрик флика (Фаза 2A): сегментация + четыре метрики + честность."""
from typing import List, Sequence, Tuple

from aim_metrics import FrameSample
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.metrics.flick_phase import (FlickPhaseReport, MIN_FLICKS_FOR_PHASE,
                                        compute_flick_phases, format_flick_phases)


def _ctx(fps: float = 60.0) -> ClipContext:
    return ClipContext(player_id="p", clip_id="c", fps=fps,
                       width=1920, height=1080, frame_count=10000)


def _flick(offsets: Sequence[Tuple[float, float]], start: int = 100,
           kind: str = "flick", speed: float = 50.0,
           track_id: int = 1) -> Episode:
    """Синтетический эпизод из ряда (dx_hu, dy_hu); radial = hypot."""
    samples = tuple(
        FrameSample(frame_idx=start + i, dx_hu=dx, dy_hu=dy,
                    radial_hu=(dx * dx + dy * dy) ** 0.5, head_height_px=63.0)
        for i, (dx, dy) in enumerate(offsets))
    return Episode(track_id=track_id, start_frame=start,
                   end_frame=start + len(offsets) - 1, samples=samples,
                   kind=kind, distance_bucket="mid", multi_enemy=False,
                   multi_from_frame=None, duel_frames=0,
                   peak_closing_speed_hu_s=speed)


# радиальные ряды по оси X (dy=0), чтобы radial == |dx|
def _x(radials: Sequence[float]) -> List[Tuple[float, float]]:
    return [(r, 0.0) for r in radials]


# ---- гейт флика ----------------------------------------------------------

def test_non_flick_episodes_ignored():
    eps = [_flick(_x([3, 0.6, 0.3, 0.3, 0.3]), kind="hold"),
           _flick(_x([3, 0.6, 0.3, 0.3, 0.3]), speed=5.0)]  # медленный
    rep = compute_flick_phases(eps, _ctx())
    assert rep.flicks_analysed == 0
    assert rep.phase_confidence == "insufficient"


# ---- сегментация: arrived / settled --------------------------------------

def test_not_arrived_excluded():
    # offset никогда не входит в near-band (0.8)
    rep = compute_flick_phases([_flick(_x([3, 2, 1.5, 1.2, 1.0, 0.9]))], _ctx())
    assert rep.flicks_analysed == 1 and rep.flicks_arrived == 0
    assert rep.flicks_settled == 0
    assert rep.phases[0].arrived is False and rep.phases[0].settled is False
    assert rep.settle_time_frames_median is None


def test_arrived_but_not_settled_excluded():
    # входит в band, но нет 3 подряд <= 0.35
    rep = compute_flick_phases([_flick(_x([3, 0.7, 0.3, 0.5, 0.3, 0.5, 0.3]))],
                               _ctx())
    p = rep.phases[0]
    assert p.arrived is True and p.settled is False
    assert p.settle_time_frames is None
    assert rep.flicks_arrived == 1 and rep.flicks_settled == 0


# ---- settle_time ---------------------------------------------------------

def test_settle_time_frames_and_ms():
    # b на index2 (0.6<=0.8); стабильно (<=0.35) с index5..7 → s=index5
    rep = compute_flick_phases(
        [_flick(_x([3, 1, 0.6, 0.4, 0.4, 0.3, 0.3, 0.3]), start=100)], _ctx(60))
    p = rep.phases[0]
    assert p.settled is True
    assert p.settle_time_frames == 3          # кадр105 − кадр102
    assert rep.settle_time_frames_median == 3


# ---- flick_overshoot_hu: истинный перелёт через центр ---------------------

def test_true_overshoot_measured_on_axis_crossing():
    # dx пересекает центр: +...+ затем -0.6 → перелёт 0.6
    offs = [(3, 0), (1.5, 0), (0.5, 0), (-0.6, 0), (-0.4, 0),
            (-0.2, 0), (-0.1, 0), (-0.1, 0)]
    rep = compute_flick_phases([_flick(offs, start=100)], _ctx())
    p = rep.phases[0]
    assert p.settled is True
    assert p.flick_overshoot_hu == 0.6
    assert p.overshoot_evidence_frame == 103   # кадр смены знака (пик)


def test_jitter_near_target_is_not_overshoot():
    # микродрожь у цели БЕЗ смены знака → overshoot 0 (регрессия старой формулы)
    rep = compute_flick_phases(
        [_flick(_x([3, 1, 0.3, 0.2, 0.4, 0.3, 0.3, 0.3]))], _ctx())
    assert rep.phases[0].flick_overshoot_hu == 0.0
    assert rep.phases[0].overshoot_evidence_frame is None


# ---- settle_jitter_hu по производной -------------------------------------

def test_jitter_uses_derivative_not_spread():
    smooth = _flick(_x([3, 1, 0.6, 0.5, 0.4, 0.3, 0.3, 0.3]))
    jerky = _flick(_x([3, 1, 0.6, 0.1, 0.5, 0.05, 0.3, 0.3, 0.3]))
    j_smooth = compute_flick_phases([smooth], _ctx()).phases[0].settle_jitter_hu
    j_jerky = compute_flick_phases([jerky], _ctx()).phases[0].settle_jitter_hu
    assert j_jerky > j_smooth


# ---- correction_path_hu --------------------------------------------------

def test_correction_path_sums_absolute_travel():
    # settle-сегмент [b..s]: b=index2 (0.6), s=index5 (три 0.3 подряд с index5)
    # radial: 0.6,0.4,0.4,0.3,0.3,0.3 → путь = |.4-.6|+|.4-.4|+|.3-.4|+... по [b..s]
    rep = compute_flick_phases(
        [_flick(_x([3, 1, 0.6, 0.4, 0.4, 0.3, 0.3, 0.3]))], _ctx())
    # [b..s] = index2..5 = 0.6,0.4,0.4,0.3 → пути 0.2+0.0+0.1 = 0.3
    assert rep.phases[0].correction_path_hu == 0.3


# ---- confidence ----------------------------------------------------------

def test_confidence_thresholds():
    good = _x([3, 1, 0.6, 0.3, 0.3, 0.3])   # usable-флик
    assert compute_flick_phases([], _ctx()).phase_confidence == "insufficient"
    two = compute_flick_phases([_flick(good), _flick(good)], _ctx())
    assert two.flicks_settled == 2 and two.phase_confidence == "hypothesis"
    three = compute_flick_phases([_flick(good)] * MIN_FLICKS_FOR_PHASE, _ctx())
    assert three.phase_confidence == "diagnosis"


# ---- медианы на смеси ----------------------------------------------------

def test_medians_over_usable_only():
    usable = _flick(_x([3, 1, 0.6, 0.3, 0.3, 0.3]))
    not_arrived = _flick(_x([3, 2, 1.5, 1.2]))
    rep = compute_flick_phases([usable, not_arrived, usable, usable], _ctx())
    assert rep.flicks_analysed == 4 and rep.flicks_settled == 3
    assert rep.settle_time_frames_median is not None


# ---- формат --------------------------------------------------------------

def test_format_mentions_settle_ms_and_confidence():
    rep = compute_flick_phases([_flick(_x([3, 1, 0.6, 0.3, 0.3, 0.3]))], _ctx())
    text = format_flick_phases(rep, _ctx())
    assert "ФАЗЫ ФЛИКА" in text
    assert "мс" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.metrics.flick_phase'`.

- [ ] **Step 3: Write minimal implementation**

Создать `engine/metrics/flick_phase.py`:

```python
# -*- coding: utf-8 -*-
"""Stage 5 (Фаза 2A): фаз-метрики флика — разложение наведения на баллистику
и доводку.

Обогащает correction: было «итог» (перелёт/недолёт), стало «+ как флик пришёл».
Каждый флик режется по ряду offset(t)=radial_hu на баллистику (старт → первый
вход в near-band) и settle (вход → стабилизация). Четыре метрики (все считает
движок): overshoot (истинный перелёт через центр по знаковым осям), settle_time
(скорость доводки), settle_jitter (рывковость по производной), correction_path
(суммарный путь доводки = эффективность).

Кавеат наследуется от correction: output-space прокси; граница фаз и конец
settle — эвристика (выстрела в данных нет), не механика мыши.
"""
from dataclasses import dataclass
from statistics import median, pstdev
from typing import List, Optional, Sequence, Tuple

from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.metrics.correction import DEADBAND_HU, MIN_FLICK_SPEED_HU_S

NEAR_BAND_HU = 0.8            # граница баллистика↔settle (вход в band)
SETTLE_TOL_HU = 0.35         # тесный допуск «на цели»
SETTLE_STABLE_FRAMES = 3     # K: сколько кадров держать допуск = «успокоился»
MIN_FLICKS_FOR_PHASE = 3     # порог confidence фаз


@dataclass(frozen=True)
class FlickPhase:
    """Пофликовая запись (usable = arrived and settled; иначе метрики = None)."""
    episode_index: int          # 1-based, как в format_episodes/correction
    start_frame: int
    arrived: bool
    settled: bool
    flick_overshoot_hu: Optional[float]
    settle_time_frames: Optional[int]
    settle_jitter_hu: Optional[float]
    correction_path_hu: Optional[float]
    overshoot_evidence_frame: Optional[int]


@dataclass(frozen=True)
class FlickPhaseReport:
    flicks_analysed: int         # прошли гейт флика (kind + скорость)
    flicks_arrived: int          # вошли в near-band
    flicks_settled: int          # = usable (участвуют в медианах)
    flick_overshoot_hu_median: Optional[float]
    settle_time_frames_median: Optional[float]
    settle_jitter_hu_median: Optional[float]
    correction_path_hu_median: Optional[float]
    phase_confidence: str        # diagnosis | hypothesis | insufficient
    phases: Tuple[FlickPhase, ...]


def _ballistic_entry(radials: Sequence[float], near_band_hu: float) -> Optional[int]:
    """Первый индекс входа в near-band (конец баллистики / начало settle)."""
    return next((i for i, r in enumerate(radials) if r <= near_band_hu), None)


def _settle_index(radials: Sequence[float], b: int, tol: float,
                  k: int) -> Optional[int]:
    """Первый индекс устойчивого прогона: >= k подряд radial <= tol.

    Возвращает индекс ПЕРВОГО кадра прогона (момент «успокоился»), иначе None.
    """
    run = 0
    for j in range(b, len(radials)):
        if radials[j] <= tol:
            run += 1
            if run >= k:
                return j - k + 1
        else:
            run = 0
    return None


def _axis_overshoot(values: Sequence[float],
                    deadband: float) -> Tuple[float, Optional[int]]:
    """Истинный перелёт по знаковой оси: величина захода за центр после смены
    знака. (0, None), если ось не пересекает центр за deadband."""
    first = next((i for i, v in enumerate(values) if abs(v) >= deadband), None)
    if first is None:
        return 0.0, None
    initial_positive = values[first] > 0
    for i in range(first + 1, len(values)):
        if abs(values[i]) >= deadband and (values[i] > 0) != initial_positive:
            opp = [(abs(values[j]), j) for j in range(i, len(values))
                   if (values[j] > 0) != initial_positive]
            mag, idx = max(opp)
            return mag, idx
    return 0.0, None


def _usable_phase(ep: Episode, index: int, near_band_hu: float, settle_tol_hu: float,
                  stable_frames: int, deadband_hu: float) -> FlickPhase:
    """Разложение одного (уже прошедшего гейт) флика на фазы + метрики."""
    frames = [s.frame_idx for s in ep.samples]
    radials = [s.radial_hu for s in ep.samples]
    b = _ballistic_entry(radials, near_band_hu)
    if b is None:
        return FlickPhase(index, ep.start_frame, False, False,
                          None, None, None, None, None)
    s = _settle_index(radials, b, settle_tol_hu, stable_frames)
    if s is None:
        return FlickPhase(index, ep.start_frame, True, False,
                          None, None, None, None, None)

    over_x, ix = _axis_overshoot([smp.dx_hu for smp in ep.samples[:s + 1]],
                                 deadband_hu)
    over_y, iy = _axis_overshoot([smp.dy_hu for smp in ep.samples[:s + 1]],
                                 deadband_hu)
    overshoot, ev_local = (over_y, iy) if over_y > over_x else (over_x, ix)
    ev_frame = frames[ev_local] if ev_local is not None else None

    seg = radials[b:s + 1]
    deltas = [seg[j] - seg[j - 1] for j in range(1, len(seg))]
    jitter = pstdev(deltas) if len(deltas) >= 1 else 0.0
    path = sum(abs(d) for d in deltas)
    return FlickPhase(
        episode_index=index, start_frame=ep.start_frame,
        arrived=True, settled=True,
        flick_overshoot_hu=round(overshoot, 3),
        settle_time_frames=frames[s] - frames[b],
        settle_jitter_hu=round(jitter, 3),
        correction_path_hu=round(path, 3),
        overshoot_evidence_frame=ev_frame,
    )


def compute_flick_phases(episodes: Sequence[Episode], ctx: ClipContext,
                         near_band_hu: float = NEAR_BAND_HU,
                         settle_tol_hu: float = SETTLE_TOL_HU,
                         stable_frames: int = SETTLE_STABLE_FRAMES,
                         deadband_hu: float = DEADBAND_HU,
                         min_flick_speed_hu_s: float = MIN_FLICK_SPEED_HU_S,
                         ) -> FlickPhaseReport:
    phases: List[FlickPhase] = []
    for i, ep in enumerate(episodes, start=1):
        if ep.kind != "flick" or ep.peak_closing_speed_hu_s < min_flick_speed_hu_s:
            continue
        phases.append(_usable_phase(ep, i, near_band_hu, settle_tol_hu,
                                    stable_frames, deadband_hu))

    usable = [p for p in phases if p.settled]

    def _med(attr: str) -> Optional[float]:
        vals = [getattr(p, attr) for p in usable]
        return round(median(vals), 3) if vals else None

    if not usable:
        conf = "insufficient"
    elif len(usable) >= MIN_FLICKS_FOR_PHASE:
        conf = "diagnosis"
    else:
        conf = "hypothesis"

    return FlickPhaseReport(
        flicks_analysed=len(phases),
        flicks_arrived=sum(1 for p in phases if p.arrived),
        flicks_settled=len(usable),
        flick_overshoot_hu_median=_med("flick_overshoot_hu"),
        settle_time_frames_median=(median([p.settle_time_frames for p in usable])
                                   if usable else None),
        settle_jitter_hu_median=_med("settle_jitter_hu"),
        correction_path_hu_median=_med("correction_path_hu"),
        phase_confidence=conf,
        phases=tuple(phases),
    )


def format_flick_phases(report: FlickPhaseReport, ctx: ClipContext) -> str:
    """Человеко-читаемое разложение (CLI), рядом с format_correction."""
    r = report
    ms = (None if r.settle_time_frames_median is None
          else round(1000 * r.settle_time_frames_median / ctx.fps))
    lines = [
        "=== ФАЗЫ ФЛИКА (баллистика → доводка) ===",
        f"  Фликов: анализ {r.flicks_analysed}, дошли {r.flicks_arrived},"
        f" оселись {r.flicks_settled}  [{r.phase_confidence}]",
        f"  Перелёт (медиана): {r.flick_overshoot_hu_median} HU",
        f"  Доводка (медиана): {r.settle_time_frames_median} кадр"
        f" ({ms} мс)",
        f"  Рывковость (медиана): {r.settle_jitter_hu_median} HU",
        f"  Путь доводки (медиана): {r.correction_path_hu_median} HU",
    ]
    for p in r.phases:
        if not p.settled:
            state = "не дошёл" if not p.arrived else "не оселся"
            lines.append(f"  #{p.episode_index:<2} старт {p.start_frame}: {state}")
            continue
        lines.append(
            f"  #{p.episode_index:<2} старт {p.start_frame}:"
            f"  перелёт {p.flick_overshoot_hu} HU,"
            f"  доводка {p.settle_time_frames} к,"
            f"  рывк {p.settle_jitter_hu},"
            f"  путь {p.correction_path_hu} HU")
    lines.append("  Кавеат: output-space прокси; конец settle — стабилизация"
                 " траектории, не реальный выстрел.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py -q`
Expected: PASS (все тесты).

- [ ] **Step 5: Commit**

```bash
git add engine/metrics/flick_phase.py tests/test_flick_phase.py
git commit -m "feat(engine): фаз-метрики флика — баллистика/settle, 4 метрики, confidence"
```

---

### Task 2: Встройка агрегатов в `correction`-finding

**Files:**
- Modify: `engine/report.py` (`_correction_finding`, строки ~167-205; импорт вверху)
- Test: `tests/test_correction_phase_report.py`

**Interfaces:**
- Consumes: `engine.metrics.flick_phase.compute_flick_phases`, `FlickPhaseReport`.
- Produces: `_correction_finding(...)["values"]` дополнительно содержит `flick_overshoot_hu_median`, `settle_time_frames_median`, `settle_time_ms_median`, `settle_jitter_hu_median`, `correction_path_hu_median`, `flicks_arrived`, `flicks_settled`, `phase_confidence`. Старые ключи не тронуты.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_correction_phase_report.py`:

```python
# -*- coding: utf-8 -*-
"""Встройка фаз-метрик в correction-finding (Фаза 2A) — синтетика, без dataset."""
from aim_metrics import FrameSample
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.metrics.flick_phase import compute_flick_phases
from engine.report import _correction_finding


def _ctx(fps: float = 60.0) -> ClipContext:
    return ClipContext(player_id="p", clip_id="c", fps=fps,
                       width=1920, height=1080, frame_count=10000)


def _flick(radials, start=100, track_id=1) -> Episode:
    samples = tuple(
        FrameSample(frame_idx=start + i, dx_hu=r, dy_hu=0.0,
                    radial_hu=r, head_height_px=63.0)
        for i, r in enumerate(radials))
    return Episode(track_id=track_id, start_frame=start,
                   end_frame=start + len(radials) - 1, samples=samples,
                   kind="flick", distance_bucket="mid", multi_enemy=False,
                   multi_from_frame=None, duel_frames=0,
                   peak_closing_speed_hu_s=50.0)


def test_correction_values_keep_old_keys_and_gain_phase_keys():
    eps = [_flick([3, 1, 0.6, 0.3, 0.3, 0.3], start=100, track_id=1)]
    finding = _correction_finding(eps, _ctx(), duel_hu=3.0)
    values = finding["values"]
    # старые ключи Фазы 1 на месте (от них зависит build_criterion)
    for key in ("flicks_total", "flicks_analysed", "x_overshoots",
                "x_undershoots", "y_overshoots", "y_undershoots"):
        assert key in values
    # новые фаз-ключи присутствуют и совпадают с compute_flick_phases
    ph = compute_flick_phases(eps, _ctx())
    assert values["settle_time_frames_median"] == ph.settle_time_frames_median
    assert values["flick_overshoot_hu_median"] == ph.flick_overshoot_hu_median
    assert values["correction_path_hu_median"] == ph.correction_path_hu_median
    assert values["phase_confidence"] == ph.phase_confidence
    assert values["flicks_settled"] == ph.flicks_settled
    # settle_time_ms выведен из кадров и fps
    assert values["settle_time_ms_median"] == round(
        1000 * ph.settle_time_frames_median / 60.0)


def test_phase_keys_null_when_no_usable_flicks():
    eps = [_flick([3, 2, 1.5, 1.2], start=100)]     # не дошёл
    values = _correction_finding(eps, _ctx(), duel_hu=3.0)["values"]
    assert values["settle_time_frames_median"] is None
    assert values["settle_time_ms_median"] is None
    assert values["phase_confidence"] == "insufficient"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_correction_phase_report.py -q`
Expected: FAIL — `KeyError: 'settle_time_frames_median'` (ключей ещё нет).

- [ ] **Step 3: Write minimal implementation**

В `engine/report.py` добавить импорт рядом с существующим импортом correction:

```python
from engine.metrics.flick_phase import compute_flick_phases
```

В `_correction_finding` после строки `rep = compute_correction(episodes, ctx, duel_hu=duel_hu)` добавить:

```python
    ph = compute_flick_phases(episodes, ctx)
    settle_ms = (None if ph.settle_time_frames_median is None
                 else round(1000 * ph.settle_time_frames_median / ctx.fps))
```

В том же `_correction_finding` заменить словарь `"values"` (сохранив старые ключи, дописав новые):

```python
        "values": {"flicks_total": rep.flicks_total,
                   "flicks_analysed": rep.flicks_analysed,
                   "x_overshoots": rep.x_overshoots,
                   "x_undershoots": rep.x_undershoots,
                   "y_overshoots": rep.y_overshoots,
                   "y_undershoots": rep.y_undershoots,
                   "flick_overshoot_hu_median": ph.flick_overshoot_hu_median,
                   "settle_time_frames_median": ph.settle_time_frames_median,
                   "settle_time_ms_median": settle_ms,
                   "settle_jitter_hu_median": ph.settle_jitter_hu_median,
                   "correction_path_hu_median": ph.correction_path_hu_median,
                   "flicks_arrived": ph.flicks_arrived,
                   "flicks_settled": ph.flicks_settled,
                   "phase_confidence": ph.phase_confidence},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_correction_phase_report.py tests/test_flick_phase.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/report.py tests/test_correction_phase_report.py
git commit -m "feat(report): фаз-метрики флика в values correction-finding (старые ключи целы)"
```

---

### Task 3: CLI печатает разложение фаз рядом с correction

**Files:**
- Modify: `aim_metrics.py` (блок `--correction`, строки ~384-388)

**Interfaces:**
- Consumes: `engine.metrics.flick_phase.compute_flick_phases`, `format_flick_phases`.
- Produces: при `--correction` CLI печатает и `format_correction`, и `format_flick_phases`.

- [ ] **Step 1: Прочитать текущий блок**

Открыть `aim_metrics.py` в районе строк 384-388. Ожидаемый текущий вид:

```python
        if args.correction:
            from engine.metrics.correction import (compute_correction,
                                                   format_correction)
            print(format_correction(compute_correction(episodes, ctx,
                                                        duel_hu=duel_hu), ctx))
```

- [ ] **Step 2: Дописать печать фаз**

Заменить этот блок на:

```python
        if args.correction:
            from engine.metrics.correction import (compute_correction,
                                                   format_correction)
            from engine.metrics.flick_phase import (compute_flick_phases,
                                                    format_flick_phases)
            print(format_correction(compute_correction(episodes, ctx,
                                                        duel_hu=duel_hu), ctx))
            print(format_flick_phases(compute_flick_phases(episodes, ctx), ctx))
```

- [ ] **Step 3: Прогон затронутых тестов (регрессия импорта/формата)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py tests/test_correction_phase_report.py -q`
Expected: PASS (формат покрыт `test_format_mentions_settle_ms_and_confidence`; CLI-строка — тонкая обёртка над протестированными функциями).

- [ ] **Step 4: Commit**

```bash
git add aim_metrics.py
git commit -m "feat(cli): печать фаз-метрик флика рядом с correction"
```

---

### Task 4: Зелёный прогон и проверка отсутствия регрессий

- [ ] **Step 1: Прогнать затронутые + смежные наборы**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py tests/test_correction_phase_report.py tests/test_correction.py -q`
Expected: PASS. `test_correction.py` — не тронут, но подтверждает, что старый `correction` цел.

- [ ] **Step 2: Проверить, что фаз-встройка не сломала сбор отчёта нигде**

Run: `.\.venv\Scripts\python.exe -m pytest -q --continue-on-collection-errors --ignore=tests/test_backend_api.py --ignore=tests/test_coach_client.py`
Expected: те же pre-existing dataset-падения (`FileNotFoundError` на `dataset1/*.xml`), НО ноль НОВЫХ падений из-за фаз-метрик. Наборы `test_flick_phase`/`test_correction_phase_report`/`test_correction` зелёные.

> Заметка реализатору: `.venv` не содержит fastapi/anthropic/sqlmodel и `dataset1/` отсутствует — это pre-existing окружение, НЕ регрессия. Ориентир — отсутствие НОВЫХ падений относительно старого baseline.

- [ ] **Step 3: Финальный коммит (если остались правки)**

```bash
git add -A
git commit -m "test: зелёный прогон Фазы 2A — фаз-метрики флика"
```

---

## Self-Review

**Spec coverage (2026-07-07-phase2a-flick-phase-metrics-design.md):**
- Сегментация `offset(t)` на баллистику/settle (Вариант A) → Task 1 (`_ballistic_entry`, `_settle_index`). ✅
- `flick_overshoot_hu` истинный перелёт по знаковым осям → Task 1 (`_axis_overshoot`), тест `test_true_overshoot...` + регрессия `test_jitter_near_target_is_not_overshoot`. ✅
- `settle_time_frames` + `settle_time_ms` → Task 1 (кадры) + Task 2 (мс в values). ✅
- `settle_jitter_hu` по производной → Task 1 (`pstdev(deltas)`), тест `test_jitter_uses_derivative_not_spread`. ✅
- `correction_path_hu` = Σ|Δradial| → Task 1, тест `test_correction_path...`. ✅
- Медиана по usable + `phase_confidence` (insufficient/hypothesis/diagnosis) → Task 1, тест `test_confidence_thresholds`. ✅
- Исключение «не дошёл»/«не оселся» → Task 1, тесты `test_not_arrived...`/`test_arrived_but_not_settled...`. ✅
- Гейт флика как у correction → Task 1, тест `test_non_flick_episodes_ignored`. ✅
- Встройка в `correction.values` без слома старых ключей → Task 2, тест `test_correction_values_keep_old_keys...`. ✅
- Новый модуль `engine/metrics/flick_phase.py` (отдельная ответственность) → Task 1. ✅
- `format_flick_phases` для CLI → Task 1 (функция) + Task 3 (проводка). ✅
- Границы (не трогаем каталог/валидатор/промпт/фронт/criterion/петлю) → отражено в Global Constraints и объёме тасков. ✅

**Placeholder scan:** полный код в каждом шаге; тела тестов настоящие; команды с ожидаемым выводом. Плейсхолдеров нет.

**Type consistency:** `FlickPhase`/`FlickPhaseReport` поля и `compute_flick_phases`/`format_flick_phases` сигнатуры согласованы между Task 1 (определение), Task 2 (потребление `compute_flick_phases`, чтение `*_median`/`flicks_*`/`phase_confidence`) и Task 3 (обе функции). Ключи `values` в Task 2 совпадают с полями `FlickPhaseReport` + производный `settle_time_ms_median`. `_correction_finding` сигнатура (`episodes, ctx, duel_hu`) — как в текущем `report.py`.
