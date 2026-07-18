# Фаза 4: Input-space, качество сигнала фликов, severity, in-game каталог — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Починить сигнал фаз-метрик на дырявом YOLO-треке, ввести cm/360 и см-эквивалент перелёта, опубликовать severity_ratio как факт движка с заземлённым гейтом порядка дриллов, добавить in-game ветку каталога с `training_platform`.

**Architecture:** Четыре независимых компонента поверх main (Фаза 3 влита): (1) `flick_phase` переезжает в кадровое пространство + гейт плотности; (2) новый `engine/input_space.py` с конверсией HU→см; (3) `severity_ratio` в findings + гейт монотонности в `coach/validate.py`; (4) параллельные in-game ветки в `coach/drill_catalog.py` + `training_platform` от CLI/API/формы до меню валидатора. Схема отчёта 1.2→1.3 аддитивно, `METRICS_VERSION` 2→3.

**Tech Stack:** Python 3, pytest (синтетика, без видео/БД/сети), React (только UploadForm/api.js), спека `docs/superpowers/specs/2026-07-16-engine-input-space-and-severity-design.md`.

## Global Constraints

- **Числа считает ТОЛЬКО движок**; нет сигнала — движок молчит (`None`), не догадывается.
- **Кросс-метрического ранга severity НЕТ** — ratio только внутри метрики.
- `severity_ratio: Optional[float]`, сериализуется через `_r()` (NaN → None), **никогда сырым числом**.
- **Между введением cm-полей и их заземлением в валидаторе не существует ни одного коммита** (Task 3 — атомарный).
- `METRICS_VERSION` 2→**3** и `SCHEMA_VERSION` "1.2"→**"1.3"** поднимаются в Task 1 (первый коммит, меняющий определения/поля); последующие задачи добавляют поля уже под 1.3.
- Ручки (все `# некалибр.`): `MIN_FLICK_DETECTION_DENSITY = 0.7`, `SENS_HIGH_CM360 = 30.0`, `SENS_LOW_CM360 = 60.0`, `BIAS_HIGH_HU = 0.5`, `CORRECTION_HIGH_SHARE = 0.5`.
- Константы Valorant: `VALORANT_YAW_DEG_PER_COUNT = 0.07`, `VALORANT_HFOV_DEG = 103.0`.
- `training_platform` — user-supplied факт (`"kovaaks" | "ingame" | None`), carried verbatim, never inferred; `None` схлопывается в ingame-меню.
- Старые drill_id каталога НЕ трогать (история 2B ключуется на них).
- Фронт: только UploadForm/api.js; граница — `cd frontend; npm run build`.
- Тесты запускать: `.\.venv\Scripts\python.exe -m pytest -q` (venv `.venv\`, НЕ `venv\`).
- Работа на ветке `phase4-input-space-severity` от `main`.

---

### Task 0: Ветка

- [ ] **Step 1:** `git switch -c phase4-input-space-severity main`

---

### Task 1: flick_phase — settle в кадровом пространстве, jitter по смежным дельтам, None-контракт медиан, версии

Сейчас `_settle_index` считает «k подряд» по индексам сэмплов (`engine/metrics/flick_phase.py:61-75`): на дырявом YOLO-треке 3 «подряд» сэмпла растягиваются на 15 кадров — ложное «оселся». Jitter клеит дельты через дырку (завышение). `_med` (строки 149-151) упадёт TypeError на первом же `settle_jitter_hu=None`.

**Files:**
- Modify: `engine/metrics/flick_phase.py`
- Modify: `engine/report.py` (SCHEMA_VERSION, values `flicks_jitter_n`)
- Modify: `engine/version.py` (METRICS_VERSION)
- Test: `tests/test_flick_phase.py` (дополнить), `tests/test_report.py` не трогать (прогнать)

**Interfaces:**
- Produces: `_settle_index(frames: Sequence[int], radials: Sequence[float], b: int, tol: float, k: int) -> Optional[int]`; `FlickPhaseReport.flicks_jitter_n: int`; `FlickPhase.settle_jitter_hu` теперь может быть `None` у settled-флика; `METRICS_VERSION = 3`; `SCHEMA_VERSION = "1.3"`.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_flick_phase.py` (хелперы `_flick`/`_x`/`_ctx` уже в файле; для дырок нужен новый хелпер с явными кадрами):

```python
def _flick_frames(pairs, start: int = 100, kind: str = "flick",
                  speed: float = 50.0, track_id: int = 1) -> Episode:
    """Эпизод из (frame_offset, radial): кадры задаются явно — для дырок."""
    samples = tuple(
        FrameSample(frame_idx=start + fo, dx_hu=r, dy_hu=0.0,
                    radial_hu=abs(r), head_height_px=63.0)
        for fo, r in pairs)
    return Episode(track_id=track_id, start_frame=start,
                   end_frame=start + pairs[-1][0], samples=samples,
                   kind=kind, distance_bucket="mid", multi_enemy=False,
                   multi_from_frame=None, duel_frames=0,
                   peak_closing_speed_hu_s=speed)


# ---- Фаза 4: settle в кадровом пространстве -------------------------------
# ВАЖНО: у всех дырявых эпизодов ниже плотность >= 0.7 — Task 2 введёт гейт
# плотности, и более дырявая синтетика стала бы sparse, сломав эти тесты.

def test_gap_inside_settle_run_resets_it():
    # <=0.35 держится 2 кадра, потом сброс, изолированный 0.3@9 не в счёт:
    # НЕ «оселся». Плотность 7/10 = 0.7.
    ep = _flick_frames([(0, 3.0), (1, 0.6), (2, 0.3), (3, 0.3), (4, 0.5),
                        (5, 0.5), (9, 0.3)])
    rep = compute_flick_phases([ep], _ctx())
    p = rep.phases[0]
    assert p.arrived is True and p.settled is False


def test_contiguous_settle_after_gap_still_qualifies():
    # дырка до band (кадры 3-4), но после неё 3 кадрово-смежных <= 0.35 —
    # оселся. Плотность 7/9 = 0.78.
    ep = _flick_frames([(0, 3.0), (1, 2.0), (2, 1.5), (5, 0.6), (6, 0.3),
                        (7, 0.3), (8, 0.3)])
    rep = compute_flick_phases([ep], _ctx())
    assert rep.phases[0].settled is True


def test_jitter_none_when_fewer_than_two_adjacent_pairs():
    # подход к settle дырявый: в сегменте b..s (кадры 2,4,6) ноль кадрово-
    # смежных пар — jitter None. Settle-прогон (6,7,8) смежный — settled True.
    # Плотность 7/9 = 0.78.
    ep = _flick_frames([(0, 3.0), (1, 2.0), (2, 0.6), (4, 0.4), (6, 0.3),
                        (7, 0.3), (8, 0.3)])
    rep = compute_flick_phases([ep], _ctx())
    p = rep.phases[0]
    assert p.settled is True
    assert p.settle_jitter_hu is None          # не мусор из склеек через дырки
    assert rep.flicks_jitter_n == 0
    assert rep.settle_jitter_hu_median is None  # и отчёт не падает (нет TypeError)


def test_jitter_median_gated_by_flicks_jitter_n():
    # 3 settled-флика (хватает на diagnosis), но jitter дал только один —
    # медиана рывковости обязана молчать. У clean длинный подход: сегмент b..s
    # содержит >= 2 смежных пар (иначе и он дал бы None по новому контракту).
    clean = _x([3, 2, 1, 0.7, 0.5, 0.3, 0.3, 0.3])
    holey = [(0, 3.0), (1, 2.0), (2, 0.6), (4, 0.4), (6, 0.3), (7, 0.3),
             (8, 0.3)]
    eps = [_flick(clean, start=100, track_id=1),
           _flick_frames(holey, start=300, track_id=2),
           _flick_frames(holey, start=500, track_id=3)]
    rep = compute_flick_phases(eps, _ctx())
    assert rep.flicks_settled == 3
    assert rep.phase_confidence == "diagnosis"
    assert rep.flicks_jitter_n == 1
    assert rep.settle_jitter_hu_median is None
```

- [ ] **Step 2: Прогнать — падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py -q`
Expected: FAIL (`_flick_frames`-тесты: ложный settled / TypeError в median / нет атрибута flicks_jitter_n)

- [ ] **Step 3: Реализация в `engine/metrics/flick_phase.py`**

Заменить `_settle_index`:

```python
def _settle_index(frames: Sequence[int], radials: Sequence[float], b: int,
                  tol: float, k: int) -> Optional[int]:
    """Первый индекс устойчивого прогона в КАДРОВОМ пространстве.

    Прогон продолжается только по кадрово-смежным сэмплам (frame ровно +1);
    разрыв кадра начинает прогон заново (Фаза 4: на дырявом YOLO-треке «3 подряд
    сэмпла» иначе растягиваются на 15 кадров — ложное «оселся»). Квалификация —
    прогон покрывает >= k подряд идущих кадров.
    """
    run_start: Optional[int] = None
    for j in range(b, len(radials)):
        if radials[j] > tol:
            run_start = None
            continue
        if run_start is None or frames[j] != frames[j - 1] + 1:
            run_start = j                      # разрыв кадра = новый прогон
        if frames[j] - frames[run_start] + 1 >= k:
            return run_start
    return None
```

В `_usable_phase` — новый вызов и jitter только по смежным парам:

```python
    s = _settle_index(frames, radials, b, settle_tol_hu, stable_frames)
```

и заменить блок `seg/deltas/jitter/path`:

```python
    seg_frames = frames[b:s + 1]
    seg = radials[b:s + 1]
    # jitter — только кадрово-смежные дельты: дельта через дырку = склейка двух
    # движений, завышала pstdev на ровном месте. < 2 смежных пар -> None.
    adjacent = [seg[j] - seg[j - 1] for j in range(1, len(seg))
                if seg_frames[j] == seg_frames[j - 1] + 1]
    jitter = round(pstdev(adjacent), 3) if len(adjacent) >= 2 else None
    # путь остаётся суммой |Δ| по всем сэмплам — при дырках это нижняя оценка
    path = sum(abs(seg[j] - seg[j - 1]) for j in range(1, len(seg)))
    return FlickPhase(
        episode_index=index, start_frame=ep.start_frame,
        arrived=True, settled=True,
        flick_overshoot_hu=round(overshoot, 3),
        settle_time_frames=frames[s] - frames[b],
        settle_jitter_hu=jitter,
        correction_path_hu=round(path, 3),
        overshoot_evidence_frame=ev_frame,
    )
```

В `FlickPhaseReport` добавить поле после `flicks_settled`:

```python
    flicks_jitter_n: int         # settled-флики, реально давшие jitter (не None)
```

В `compute_flick_phases` — `_med` фильтрует None, jitter-медиана гейтится своим n:

```python
    def _med(attr: str) -> Optional[float]:
        vals = [getattr(p, attr) for p in usable
                if getattr(p, attr) is not None]
        return round(median(vals), 3) if vals else None

    jitter_vals = [p.settle_jitter_hu for p in usable
                   if p.settle_jitter_hu is not None]
    # медиана рывковости молчит, пока фликов с честным jitter меньше порога —
    # иначе confidence по settled дал бы утвердительный язык про 1 флик
    jitter_median = (round(median(jitter_vals), 3)
                     if len(jitter_vals) >= MIN_FLICKS_FOR_PHASE else None)
```

и в конструкторе отчёта:

```python
        flicks_jitter_n=len(jitter_vals),
        ...
        settle_jitter_hu_median=jitter_median,
```

Обновить кавеат в `format_flick_phases` (последняя строка перед return):

```python
    lines.append("  Кавеат: output-space прокси; конец settle — стабилизация"
                 " траектории, не реальный выстрел; путь — нижняя оценка при"
                 " пропусках детекции.")
```

- [ ] **Step 4: Версии + values**

`engine/version.py`: комментарий и значение —

```python
# v1 — методика до Фазы 3 (записи без поля). v2 — атрибуция цели + гейт пре-айма.
# v3 — Фаза 4: settle в кадровом пространстве, jitter по смежным дельтам,
#      гейт плотности детекций (меняет flicks_analysed/медианы/счётчики).
METRICS_VERSION = 3
```

`engine/report.py`: `SCHEMA_VERSION = "1.3"`; в values `_correction_finding` после `"flicks_settled"` добавить:

```python
                   "flicks_jitter_n": ph.flicks_jitter_n,
```

- [ ] **Step 5: Прогнать flick_phase + report + полный сьют**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_flick_phase.py tests/test_report.py tests/test_correction_phase_report.py -q`, затем `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. Легальные правки существующих тестов здесь ровно две (обе — следствия спеки, не подгонка): (1) `schema_version == "1.2"` → "1.3"; (2) существующий jitter-тест, чей сегмент b..s содержит < 2 кадрово-смежных пар, по новому контракту ожидает `None` вместо `0.0` — обновить ожидание или удлинить подход в синтетике.

- [ ] **Step 6: Commit**

```bash
git add engine/metrics/flick_phase.py engine/version.py engine/report.py tests/test_flick_phase.py tests/test_report.py
git commit -m "fix(engine): settle/jitter фликов в кадровом пространстве, None-контракт медиан; METRICS_VERSION=3, schema 1.3"
```

---

### Task 2: Гейт плотности детекций (страховка после починки)

**Files:**
- Modify: `engine/episodes.py` (хелпер + ручка)
- Modify: `engine/metrics/flick_phase.py`, `engine/metrics/correction.py` (гейт у ОБОИХ потребителей)
- Modify: `engine/report.py` (values `flicks_sparse`)
- Test: `tests/test_flick_phase.py`, `tests/test_correction.py` (или где тесты correction — найти `grep -l compute_correction tests/`)

**Interfaces:**
- Consumes: `Episode` (поля `samples`, `start_frame`, `end_frame`).
- Produces: `engine.episodes.detection_density(ep: Episode) -> float`; `engine.episodes.MIN_FLICK_DETECTION_DENSITY = 0.7`; `FlickPhaseReport.flicks_sparse: int`; `CorrectionReport.flicks_sparse: int`. Sparse-флик: посчитан в `flicks_sparse`, исключён из phases/verdicts/медиан/confidence.

- [ ] **Step 1: Падающие тесты**

В `tests/test_flick_phase.py`:

```python
def test_sparse_flick_counted_but_excluded():
    # density = 6 сэмплов / 15 кадров = 0.4 < 0.7 — sparse
    holey = [(0, 3.0), (3, 1.0), (6, 0.6), (12, 0.3), (13, 0.3), (14, 0.3)]
    dense = _x([3, 1, 0.6, 0.3, 0.3, 0.3])
    rep = compute_flick_phases([_flick_frames(holey, start=100, track_id=1),
                                _flick(dense, start=300, track_id=2)], _ctx())
    assert rep.flicks_sparse == 1
    assert rep.flicks_analysed == 1        # sparse не в знаменателе
    assert len(rep.phases) == 1            # и не в phases
```

В файл тестов correction (там есть свои хелперы эпизодов — использовать их стиль; если хелпера с явными кадрами нет, скопировать `_flick_frames` с импортами):

```python
def test_sparse_flick_excluded_from_correction():
    holey = [(0, 3.0), (3, 1.0), (6, 0.6), (12, 0.3), (13, 0.3), (14, 0.3)]
    ep = _flick_frames(holey)
    rep = compute_correction([ep], _ctx())
    assert rep.flicks_sparse == 1
    assert rep.flicks_analysed == 0
```

- [ ] **Step 2: Прогнать — падают** (нет атрибута `flicks_sparse`)

- [ ] **Step 3: Реализация**

`engine/episodes.py` (после дефиниции `Episode`):

```python
# Гейт плотности детекций (Фаза 4): доля кадров эпизода, где голова реально
# детектирована. Разреженный флик-трек «слишком дырявый» для фаз-метрик И для
# перелёта — гейт применяют оба потребителя.
MIN_FLICK_DETECTION_DENSITY = 0.7   # некалибр.: грубее — вердикты по дыркам


def detection_density(ep: Episode) -> float:
    """Доля кадров эпизода с детекцией головы (1.0 = трек без дырок)."""
    return len(ep.samples) / (ep.end_frame - ep.start_frame + 1)
```

`flick_phase.py`: импорт `from engine.episodes import Episode, MIN_FLICK_DETECTION_DENSITY, detection_density`; параметр `min_density: float = MIN_FLICK_DETECTION_DENSITY` у `compute_flick_phases`; в цикле после гейта скорости:

```python
        if detection_density(ep) < min_density:
            sparse += 1            # посчитан, но исключён из вердиктов/медиан
            continue
```

(`sparse = 0` перед циклом; `FlickPhaseReport` — поле `flicks_sparse: int` после `flicks_analysed`; в конструкторе `flicks_sparse=sparse`).

`correction.py`: тот же импорт/параметр/скип в цикле `compute_correction`; `CorrectionReport.flicks_sparse: int`; `flicks_sparse=sparse` в конструкторе.

`report.py` `_correction_finding` values:

```python
                   "flicks_sparse": rep.flicks_sparse,
```

- [ ] **Step 4: Прогнать оба файла тестов + полный сьют** — PASS

- [ ] **Step 5: Commit**

```bash
git add engine/episodes.py engine/metrics/flick_phase.py engine/metrics/correction.py engine/report.py tests/
git commit -m "feat(engine): гейт плотности детекций для фликов (sparse считается, но исключён)"
```

---

### Task 3: `engine/input_space.py` + cm-поля отчёта + заземление сантиметров (атомарно)

**Files:**
- Create: `engine/input_space.py`
- Modify: `engine/report.py` (clip-блок, correction values, кавеат)
- Modify: `coach/validate.py` (`_CM_NUMBER_RE`, пул, проверки)
- Test: `tests/test_input_space.py` (новый), `tests/test_report.py`, `tests/test_coach_validate.py`

**Interfaces:**
- Produces: `cm_per_360(edpi: Optional[float]) -> Optional[float]`; `hu_to_cm_equiv(hu: float, head_height_px: float, ctx: ClipContext) -> Optional[float]`; `cm_unavailable_reason(ctx: ClipContext) -> Optional[str]` (`None` = cm доступны; иначе `"нет eDPI"` / `"аспект не 16:9"`); отчёт: `clip.cm_per_360`, `clip.cm_unavailable_reason`, values correction `flick_overshoot_cm_equiv_median`.

- [ ] **Step 1: Падающие тесты `tests/test_input_space.py`**

```python
# -*- coding: utf-8 -*-
"""Input-space: cm/360 из eDPI, HU->см-эквивалент, честные отказы (Фаза 4)."""
import pytest

from engine.clip_context import ClipContext
from engine.input_space import cm_per_360, cm_unavailable_reason, hu_to_cm_equiv


def _ctx(width=1920, height=1080, edpi=280.0):
    return ClipContext(player_id="p", clip_id="c", fps=60.0, width=width,
                       height=height, frame_count=1000, edpi=edpi)


def test_cm_per_360_matches_community_calculators():
    # 360 * 2.54 / (0.07 * 280) = 46.65 (сверено с калькуляторами)
    assert cm_per_360(280.0) == pytest.approx(46.65, abs=0.01)


def test_cm_per_360_none_without_edpi():
    assert cm_per_360(None) is None


def test_cm_per_360_survives_stretched_res():
    # мышиная арифметика: ни ширины кадра, ни FOV в формуле нет
    assert cm_unavailable_reason(_ctx(width=1280, height=960)) == "аспект не 16:9"
    assert cm_per_360(_ctx(width=1280, height=960).edpi) is not None


def test_reason_no_edpi_beats_aspect():
    assert cm_unavailable_reason(_ctx(edpi=None)) == "нет eDPI"
    assert cm_unavailable_reason(_ctx()) is None


def test_hu_to_cm_equiv_monotone_and_positive():
    cm1 = hu_to_cm_equiv(1.0, 63.0, _ctx())
    cm2 = hu_to_cm_equiv(2.0, 63.0, _ctx())
    assert cm1 is not None and cm1 > 0
    assert cm2 > cm1


def test_hu_to_cm_equiv_none_when_invalid():
    assert hu_to_cm_equiv(1.0, 63.0, _ctx(edpi=None)) is None
    assert hu_to_cm_equiv(1.0, 63.0, _ctx(width=1280, height=960)) is None
```

- [ ] **Step 2: Прогнать — ModuleNotFoundError**

- [ ] **Step 3: `engine/input_space.py`**

```python
# -*- coding: utf-8 -*-
"""Input-space (Фаза 4): sens/eDPI перестают ехать в отчёт мёртвым грузом.

cm/360 — чистая мышиная арифметика (ни ширины кадра, ни FOV в формуле нет).
HU -> см — ЭКВИВАЛЕНТ, не измерение: перелёт — output-space прокси (стрейф
врага неотделим от руки), поле читается «столько руки объяснило бы перелёт
целиком». FOV-модель валидна только для 16:9 (стрельба с бедра).
"""
import math
from typing import Optional

from engine.clip_context import ClipContext

VALORANT_YAW_DEG_PER_COUNT = 0.07   # градусов на отсчёт мыши при sens 1.0
VALORANT_HFOV_DEG = 103.0           # горизонтальный FOV с бедра, 16:9

_ASPECT_16_9 = 16.0 / 9.0
_ASPECT_TOL = 0.01


def cm_per_360(edpi: Optional[float]) -> Optional[float]:
    """Сантиметров руки на полный оборот; None только при отсутствии eDPI."""
    if edpi is None or edpi <= 0:
        return None
    return 360.0 * 2.54 / (VALORANT_YAW_DEG_PER_COUNT * edpi)


def _is_16_9(ctx: ClipContext) -> bool:
    return abs(ctx.width / ctx.height - _ASPECT_16_9) <= _ASPECT_TOL


def cm_unavailable_reason(ctx: ClipContext) -> Optional[str]:
    """Почему см-эквивалент недоступен; None = доступен. Причины раздельны:
    cm/360 живёт и на stretched res, эквивалент перелёта — нет."""
    if ctx.edpi is None or ctx.edpi <= 0:
        return "нет eDPI"
    if not _is_16_9(ctx):
        return "аспект не 16:9"
    return None


def hu_to_cm_equiv(hu: float, head_height_px: float,
                   ctx: ClipContext) -> Optional[float]:
    """HU -> px -> градусы (тангенсная проекция) -> см руки через cm/360.

    При квадратных пикселях фокусное из HFOV общее для обеих осей."""
    if cm_unavailable_reason(ctx) is not None:
        return None
    px = abs(hu) * head_height_px
    half_w = ctx.width / 2.0
    focal_px = half_w / math.tan(math.radians(VALORANT_HFOV_DEG / 2.0))
    degrees = math.degrees(math.atan(px / focal_px))
    return degrees / 360.0 * cm_per_360(ctx.edpi)
```

- [ ] **Step 4: Прогнать test_input_space — PASS**

- [ ] **Step 5: Падающие тесты отчёта и валидатора**

В `tests/test_report.py` (используя существующий в файле способ построить report — найти и переиспользовать местные фикстуры/хелперы; ctx с edpi):

```python
def test_clip_block_carries_cm_per_360_and_reason():
    # ctx c edpi=280 -> cm_per_360 ~= 46.65, reason None;
    # ctx без edpi -> cm_per_360 None, reason "нет eDPI";
    # проверить оба через build_report(...)["clip"]
    ...  # конкретная сборка — по образцу соседних тестов файла


def test_correction_values_have_cm_equiv_median_or_none():
    # с edpi: ключ flick_overshoot_cm_equiv_median присутствует (float|None);
    # без edpi: значение None, отчёт сериализуется report_to_json без ошибок
    ...
```

(Тела дописать по образцу соседних тестов `tests/test_report.py` — сборка эпизодов там уже есть; ключевые assert'ы: наличие ключей, `report_to_json(report)` не падает.)

В `tests/test_coach_validate.py`:

```python
def test_invented_cm_number_is_blocked():
    # текст коуча упоминает "12.3 см", которых нет ни в clip.cm_per_360, ни в
    # values -> ошибка "не найдено в evidence-JSON"
    ...


def test_cm_per_360_from_clip_block_passes():
    # evidence["clip"]["cm_per_360"] = 46.65; текст "46.65 см" -> ошибок нет
    ...
```

(Тела — по образцу соседних HU-тестов этого файла: там есть фабрики evidence/coach-report.)

- [ ] **Step 6: Реализация отчёта — `engine/report.py`**

Импорт: `from engine.input_space import cm_per_360, cm_unavailable_reason, hu_to_cm_equiv`.

В `build_report` заменить `"clip": asdict(ctx),` на:

```python
    clip_block = asdict(ctx)
    # Input-space (Фаза 4): sens/eDPI конвертируются в физику руки. Причины
    # отсутствия раздельны: cm/360 живёт на stretched res, cm-эквивалент — нет.
    clip_block["cm_per_360"] = _r(cm_per_360(ctx.edpi), 2)
    clip_block["cm_unavailable_reason"] = cm_unavailable_reason(ctx)
```

и `"clip": clip_block,`.

В `_correction_finding` (сигнатура уже получает `ctx`) перед `return` собрать cm-медиану:

```python
    # см-эквивалент перелёта: те же usable-флики, что HU-медиана; конверсия по
    # высоте головы на кадре улики перелёта. 0-перелёт конвертируется в 0 см.
    cm_vals = []
    for p in ph.phases:
        if not p.settled or p.flick_overshoot_hu is None:
            continue
        if p.overshoot_evidence_frame is None:
            cm_vals.append(0.0 if p.flick_overshoot_hu == 0 else None)
            continue
        pep = episodes[p.episode_index - 1]
        hh = _sample_at(pep, p.overshoot_evidence_frame).head_height_px
        cm_vals.append(hu_to_cm_equiv(p.flick_overshoot_hu, hh, ctx))
    cm_known = [v for v in cm_vals if v is not None]
    cm_median = _r(median(cm_known), 2) if cm_known else None
```

(добавить `from statistics import median` вверху файла). В values:

```python
                   "flick_overshoot_cm_equiv_median": cm_median,
```

Кавеат finding'а — дополнить при наличии cm-полей: заменить строку `"caveat": (...)` на:

```python
        "caveat": ("смена знака может быть стрейфом врага — прокси-метрика по"
                   " output-space, не механика мыши"
                   + ("; см — эквивалент хода мыши, не измерение (стрейф врага"
                      " неотделим); валидно для стрельбы с бедра — Operator в"
                      " прицеле ≈ 2.5×, сигнала о зуме в данных нет"
                      if cm_median is not None else "")),
```

- [ ] **Step 7: Реализация заземления — `coach/validate.py`**

После `_HU_NUMBER_RE`:

```python
_CM_NUMBER_RE = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s*(?:см|cm)\b", re.IGNORECASE)
```

Функции (рядом с HU-аналогами):

```python
def _cm_numbers_in_text(text: str) -> List[float]:
    return [float(m.group(1).replace(",", "."))
            for m in _CM_NUMBER_RE.finditer(text)]


def _check_cm_numbers(text: str, pool: List[float], where: str) -> List[str]:
    """Каждое см-число текста должно совпасть с числом движка (по модулю,
    с допуском на округление) — та же анти-выдумка, что для HU."""
    errors = []
    for match in _CM_NUMBER_RE.finditer(text):
        raw = match.group(1)
        value = float(raw.replace(",", "."))
        digits = raw.replace(",", ".")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        tolerance = 0.5 * 10 ** -decimals + 1e-9
        if not any(abs(abs(value) - abs(known)) <= tolerance for known in pool):
            errors.append(f"число {raw} см ({where}) не найдено в evidence-JSON")
    return errors
```

Пул: в `_known_numbers` добавить (перед `return pool`):

```python
    # Фаза 4: cm-числа. clip-блок в пул раньше не входил — расширяем ЯВНО;
    # flick_overshoot_cm_equiv_median попадает автоматически через values.
    clip = evidence.get("clip") or {}
    if _is_number(clip.get("cm_per_360")):
        pool.append(float(clip["cm_per_360"]))
    for finding in evidence.get("findings", []):
        pool.extend(_cm_numbers_in_text(finding.get("statement") or ""))
        pool.extend(_cm_numbers_in_text(finding.get("caveat") or ""))
    return pool
```

Вызовы: рядом с КАЖДЫМ существующим `_check_hu_numbers(X, numbers_known, where)` (7 мест: explanation находок, summary, rationale дриллов, explanation прогресса) добавить строку `errors.extend(_check_cm_numbers(X, numbers_known, where))`.

- [ ] **Step 8: Прогнать report+validate тесты + полный сьют** — PASS

- [ ] **Step 9: Commit (единый — заземление в том же коммите, что поля)**

```bash
git add engine/input_space.py engine/report.py coach/validate.py tests/
git commit -m "feat(engine): input-space — cm/360 и см-эквивалент перелёта + заземление см в валидаторе"
```

---

### Task 4: Условная `_symmetry_note`

**Files:**
- Modify: `engine/metrics/correction.py`
- Test: `tests/` файл тестов correction

**Interfaces:**
- Consumes: `cm_per_360` (Task 3).
- Produces: `_symmetry_note(analysed: int, counts: dict, cm360: Optional[float]) -> str`; константы `SENS_HIGH_CM360 = 30.0`, `SENS_LOW_CM360 = 60.0` в correction.py.

- [ ] **Step 1: Падающие тесты** (в файле тестов correction; хелперы эпизодов там; симметричный перелёт = X и Y overshoot на ≥3 фликах):

```python
def test_symmetry_note_known_high_sens():
    # ctx.edpi=800 -> cm/360 ~16.3 < 30 -> «сенса-подобная гипотеза усиливается»
    ...
    assert "сенса высокая" in rep.symmetry_note
    assert "16.3" in rep.symmetry_note


def test_symmetry_note_known_moderate_sens():
    # ctx.edpi=280 -> 46.65 > 30 -> «смотри в сторону доводки/мышечной памяти»
    ...
    assert "сенса умеренная" in rep.symmetry_note


def test_symmetry_note_unknown_sens_keeps_old_text():
    # edpi=None -> прежний текст «похоже на сенсу (сенса-подобное)»
    ...
    assert "сенса-подобное" in rep.symmetry_note
```

- [ ] **Step 2: Прогнать — падают**

- [ ] **Step 3: Реализация**

Импорт `from engine.input_space import cm_per_360`; константы:

```python
SENS_HIGH_CM360 = 30.0   # некалибр.: быстрее ~30 см/360 сообщество зовёт высокой
SENS_LOW_CM360 = 60.0    # некалибр.: медленнее — заведомо «контрольная» сенса
```

Вызов в `compute_correction`: `symmetry_note=_symmetry_note(len(verdicts), counts, cm_per_360(ctx.edpi)),`.

Замена ветки симметрии в `_symmetry_note(analysed, counts, cm360)`:

```python
    if abs(rate_x - rate_y) <= 0.25:
        if cm360 is not None and cm360 <= SENS_HIGH_CM360:
            return (f"перелёт симметричен по осям — и сенса высокая"
                    f" ({cm360:.1f} см/360): сенса-подобная гипотеза усиливается")
        if cm360 is not None:
            return (f"перелёт симметричен по осям — но сенса умеренная"
                    f" ({cm360:.1f} см/360): смотри в сторону доводки/мышечной"
                    f" памяти")
        return "перелёт симметричен по осям — похоже на сенсу (сенса-подобное)"
```

Язык всюду гипотезный (нота, не вердикт).

- [ ] **Step 4: Прогнать + полный сьют** — PASS. Замечание: `statement` correction-находки теперь может содержать «N см/360» — пул валидатора уже собирает cm из statement (Task 3), регресс-тестов не будет.

- [ ] **Step 5: Commit**

```bash
git add engine/metrics/correction.py tests/
git commit -m "feat(engine): symmetry_note условна по cm/360 — сенса-гипотеза смотрит на сенсу"
```

---

### Task 5: `severity_ratio` во всех находках

**Files:**
- Modify: `engine/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `PLACEMENT_TARGET_FRACTION` (`engine/metrics/criterion.py`), `DEFAULT_SPREAD_HIGH_HU`/`DEFAULT_ERROR_HIGH_HU` (`engine/metrics/consistency.py`).
- Produces: ключ `"severity_ratio"` в каждой из 4 находок (`Optional[float]`, через `_r()`); константы `BIAS_HIGH_HU = 0.5`, `CORRECTION_HIGH_SHARE = 0.5` в report.py.

- [ ] **Step 1: Падающие тесты** (`tests/test_report.py`, по образцу соседних):

```python
def test_severity_ratio_consistency_uses_diagnosis_value():
    # синтетика с диагнозом repeatability (std>1, mae>1):
    # ratio обязан прийти от std, не от mae — иначе два факта в разные стороны
    ...


def test_severity_ratio_none_on_empty_clip_and_serializes():
    # build_report c episodes=[], samples=[] -> у всех 4 находок
    # severity_ratio is None, report_to_json(report) НЕ падает (allow_nan=False)
    ...


def test_severity_ratio_present_on_hypothesis():
    # величина существует при малом n -> ratio публикуется, интерпретацию
    # ограничивает confidence-лейбл
    ...
```

- [ ] **Step 2: Прогнать — падают** (нет ключа severity_ratio)

- [ ] **Step 3: Реализация — `engine/report.py`**

Импорты: `from engine.metrics.consistency import DEFAULT_ERROR_HIGH_HU, DEFAULT_SPREAD_HIGH_HU, _DIAGNOSIS_TEXT, compute_consistency` (первые два — добавить); `from engine.metrics.criterion import PLACEMENT_TARGET_FRACTION`.

Константы после `MIN_FLICKS_FOR_DIAGNOSIS`:

```python
# severity_ratio (Фаза 4): отклонение находки от ЕЁ СОБСТВЕННОГО порога —
# факт внутри метрики. Кросс-метрического ранга НЕТ: обменного курса между
# метриками взять неоткуда, порядок между ними — суждение VLM под гейтом.
BIAS_HIGH_HU = 0.5            # некалибр.: полголовы систематического смещения
CORRECTION_HIGH_SHARE = 0.5   # некалибр.: худшая ось портит > половины фликов
```

В `_placement_finding` перед `return` и в dict:

```python
    severity = (None if rep.total_gated == 0
                else (rep.n_below / rep.total_gated) / PLACEMENT_TARGET_FRACTION)
    ...
        "severity_ratio": _r(severity),
```

В `_consistency_finding`:

```python
    if rep.duel_frames == 0:
        severity = None            # нет числителя: mae/std = NaN
    else:
        std_ratio = rep.std_hu / DEFAULT_SPREAD_HIGH_HU
        mae_ratio = rep.duel_mae_hu / DEFAULT_ERROR_HIGH_HU
        # ratio от ДИАГНОЗНОЙ величины (зеркалит порядок _classify) — иначе при
        # std 1.1/mae 3.0 диагноз скажет «повторяемость», а severity от калибровки
        if rep.diagnosis == "repeatability":
            severity = std_ratio
        elif rep.diagnosis == "calibration":
            severity = mae_ratio
        else:                      # stable_accurate / insufficient: запас/общий
            severity = max(std_ratio, mae_ratio)
    ...
        "severity_ratio": _r(severity),
```

В `_bias_finding`:

```python
    severity = (None if p.y_bias_hu is None or math.isnan(p.y_bias_hu)
                else abs(p.y_bias_hu) / BIAS_HIGH_HU)
    ...
        "severity_ratio": _r(severity),
```

В `_correction_finding`:

```python
    worst = max(rep.x_overshoots, rep.x_undershoots,
                rep.y_overshoots, rep.y_undershoots)
    severity = (None if rep.flicks_analysed == 0
                else (worst / rep.flicks_analysed) / CORRECTION_HIGH_SHARE)
    ...
        "severity_ratio": _r(severity),
```

- [ ] **Step 4: Прогнать + полный сьют** — PASS (severity попадает в пул чисел валидатора автоматически через values — это желаемое поведение)

- [ ] **Step 5: Commit**

```bash
git add engine/report.py tests/test_report.py
git commit -m "feat(engine): severity_ratio — отклонение находки от собственного порога, per-metric"
```

---

### Task 6: Гейт монотонности порядка дриллов + правило в промпте

**Files:**
- Modify: `coach/validate.py`, `coach/prompt.py`
- Test: `tests/test_coach_validate.py`

**Interfaces:**
- Produces: в `validate_coach_report` — проверка: при сортировке дриллов по `priority` класс уверенности целевой находки не возрастает (`diagnosis(2) ≥ hypothesis(1) ≥ insufficient(0)`).

- [ ] **Step 1: Падающие тесты** (фабрики evidence/coach в файле уже есть):

```python
def test_drill_order_hypothesis_before_diagnosis_is_error():
    # priority 1 -> дрилл по hypothesis-находке, priority 2 -> по diagnosis
    ...
    assert any("монотонность" in e for e in errors)


def test_drill_order_insufficient_in_middle_is_error():
    # diagnosis(1), insufficient(2), hypothesis(3) -> рост класса на шаге 2->3
    ...


def test_drill_order_equal_classes_any_order_ok():
    # два diagnosis в любом порядке -> ошибок монотонности нет
    ...
```

- [ ] **Step 2: Прогнать — падают**

- [ ] **Step 3: Реализация — `coach/validate.py`**

Константа рядом с `_HEDGED_CONFIDENCES`:

```python
_CONF_RANK = {"diagnosis": 2, "hypothesis": 1, "insufficient": 0}
```

После существующего цикла по `coach.drills` (перед блоком progress):

```python
    # Гейт монотонности (Фаза 4): порядок дриллов по priority не должен ставить
    # менее уверенный класс раньше более уверенного. Жёсткий гейт — только на
    # факте движка (confidence находки); внутри класса порядок выбирает VLM.
    ranked = []
    for drill in sorted(coach.drills, key=lambda d: d.priority):
        cd = get_catalog_drill(drill.drill_id)
        if cd is None:
            continue                     # уже поймано выше
        finding = findings_by_metric.get(cd.metric)
        if finding is None:
            continue                     # уже поймано выше
        rank = _CONF_RANK.get(finding.get("confidence"))
        if rank is not None:
            ranked.append((drill.drill_id, rank))
    for (prev_id, prev_rank), (cur_id, cur_rank) in zip(ranked, ranked[1:]):
        if cur_rank > prev_rank:
            errors.append(
                f"нарушена монотонность уверенности: дрилл '{cur_id}' (класс "
                f"выше) стоит после '{prev_id}' — сортируй diagnosis ≥ "
                f"hypothesis ≥ insufficient")
```

- [ ] **Step 4: Правило в промпт — `coach/prompt.py`**

В `SYSTEM_PROMPT`, блок «ТРЕНИРОВОЧНЫЙ ПЛАН», заменить фразу «Сначала лечи диагнозы, потом гипотезы.» на:

```
Порядок приоритетов СТРОГО по классу уверенности целевой находки: сначала все \
дриллы по diagnosis-находкам, затем hypothesis, затем insufficient (проверяется \
механически). Внутри одного класса выбирай порядок сам и мотивируй в rationale; \
поле severity_ratio находки (отклонение от её порога) — подсказка для порядка \
внутри класса, между метриками ratio НЕ сравнивай.
```

- [ ] **Step 5: Прогнать + полный сьют** — PASS

- [ ] **Step 6: Commit**

```bash
git add coach/validate.py coach/prompt.py tests/test_coach_validate.py
git commit -m "feat(coach): гейт монотонности порядка дриллов по классу уверенности + severity в промпте"
```

---

### Task 7: In-game ветка каталога + `training_platform` в ClipContext + контекстное меню

**Files:**
- Modify: `engine/clip_context.py` (поле + валидация + оба контекст-билдера)
- Modify: `coach/drill_catalog.py` (9 новых дриллов, menu по платформе)
- Modify: `coach/validate.py` (меню из clip-блока), `coach/prompt.py` (меню по платформе)
- Test: `tests/test_drill_catalog.py`, `tests/test_coach_validate.py`, `tests/test_clip_context.py` (если есть; иначе в test_drill_catalog)

**Interfaces:**
- Produces: `ClipContext.training_platform: Optional[str] = None` (валидация: `None|"kovaaks"|"ingame"`); `menu_drill_ids(training_platform: Optional[str] = None) -> frozenset`; `menu_for_prompt(training_platform: Optional[str] = None) -> str`; новые drill_id: `consistency_ingame_t1_range_tempo`, `consistency_ingame_t2_dm_tempo`, `consistency_ingame_t3_dm_heads`, `bias_ingame_t1_range_placement`, `bias_ingame_t2_range_strict`, `bias_ingame_t3_dm_control`, `correction_ingame_t1_range_flicks`, `correction_ingame_t2_range_far`, `correction_ingame_t3_dm_flicks`.

- [ ] **Step 1: Падающие тесты** (`tests/test_drill_catalog.py`):

```python
def test_ingame_menu_is_exactly_four_and_kovaaks_free():
    for platform in ("ingame", None):
        ids = menu_drill_ids(platform)
        assert len(ids) == 4
        drills = [get_catalog_drill(i) for i in ids]
        assert all(d.platform != "kovaaks" for d in drills)
        # анти-сирота: у КАЖДОЙ из 4 метрик есть tier-1 вариант (bias не выпадает)
        assert {d.metric for d in drills} == set(CORE_METRICS)


def test_kovaaks_menu_is_exactly_seven():
    # placement 1 + consistency 2 + bias 2 + correction 2 — только при явном kovaaks
    ids = menu_drill_ids("kovaaks")
    assert len(ids) == 7


def test_old_drill_ids_untouched():
    # история 2B ключуется на id — переименование рвёт её
    for old in ("consistency_t1_vt_ww5t_novice", "bias_t1_vt_1w4ts_novice",
                "correction_t1_vt_pasu_novice", "placement_t1_range_preaim_walk"):
        assert get_catalog_drill(old) is not None
```

В `tests/test_coach_validate.py`:

```python
def test_kovaaks_drill_under_ingame_menu_is_error():
    # evidence["clip"]["training_platform"] отсутствует (None) ->
    # выбор consistency_t1_vt_ww5t_novice -> ошибка «не из меню»
    ...


def test_kovaaks_drill_with_explicit_kovaaks_platform_passes():
    # evidence["clip"]["training_platform"]="kovaaks" -> тот же выбор легален
    ...
```

Тест ClipContext:

```python
def test_training_platform_validated():
    ClipContext(player_id="p", clip_id="c", fps=60, width=1920, height=1080,
                frame_count=10, training_platform="kovaaks")   # ок
    with pytest.raises(ValueError):
        ClipContext(player_id="p", clip_id="c", fps=60, width=1920,
                    height=1080, frame_count=10, training_platform="csgo")
```

- [ ] **Step 2: Прогнать — падают**

- [ ] **Step 3: `engine/clip_context.py`**

Поле в `ClipContext` после `map_name` + докстрока класса: дополнить перечисление user-supplied фактов: «`sens`/`edpi`/`agent`/`map_name`/`training_platform` are user-supplied input-space facts...». В `__post_init__`:

```python
        if self.training_platform not in (None, "kovaaks", "ingame"):
            raise ValueError(
                f"training_platform must be 'kovaaks' | 'ingame' | None, "
                f"got {self.training_platform!r}")
```

`context_for_video` и `context_for_gt`: параметр `training_platform: Optional[str] = None`, проброс в конструктор.

- [ ] **Step 4: `coach/drill_catalog.py` — 9 новых дриллов**

Дописать в существующие списки CATALOG (НЕ трогая старые записи):

```python
    "consistency": [ ...существующие три...,
        CatalogDrill("consistency_ingame_t1_range_tempo",
                     "Range: одиночные в голову на стабильном темпе", "range", 1,
                     "consistency", "10 минут перед сессией",
                     "Одиночные выстрелы в голову ботам на ровном темпе — минимизируй разброс, не скорость."),
        CatalogDrill("consistency_ingame_t2_dm_tempo",
                     "Valorant DM: стабильный темп под давлением", "ingame", 2,
                     "consistency", "1 матч DM в день",
                     "Держи одинаковый ритм дуэлей: одинаковая подготовка выстрела в каждом бою."),
        CatalogDrill("consistency_ingame_t3_dm_heads",
                     "Valorant DM: только хедшоты", "ingame", 3,
                     "consistency", "1 матч DM в день",
                     "Засчитывай себе только убийства в голову — повторяемость на соревновательном темпе."),
    ],
    "bias": [ ...существующие три...,
        CatalogDrill("bias_ingame_t1_range_placement",
                     "Range: одиночная постановка с контролем попадания", "range", 1,
                     "bias", "10 минут перед сессией",
                     "Одиночный выстрел -> замри -> посмотри, куда легла пуля относительно головы. Смещение видно без тренажёра."),
        CatalogDrill("bias_ingame_t2_range_strict",
                     "Range: постановка на строгой дистанции", "range", 2,
                     "bias", "10 минут перед сессией",
                     "Та же постановка на средней/дальней дистанции — систематика смещения заметнее."),
        CatalogDrill("bias_ingame_t3_dm_control",
                     "Valorant DM: контроль первой пули", "ingame", 3,
                     "bias", "1 матч DM в день",
                     "Отслеживай, куда уходит ПЕРВАЯ пуля каждой дуэли относительно головы."),
    ],
    "correction": [ ...существующие три...,
        CatalogDrill("correction_ingame_t1_range_flicks",
                     "Range: флики на новые цели с доводкой", "range", 1,
                     "correction", "10 минут перед сессией",
                     "Осознанные флики между ботами: доводи без проскока, гаси перелёт."),
        CatalogDrill("correction_ingame_t2_range_far",
                     "Range: флики на дальние цели", "range", 2,
                     "correction", "10 минут перед сессией",
                     "Большая амплитуда — перелёт дороже; та же доводка без проскока."),
        CatalogDrill("correction_ingame_t3_dm_flicks",
                     "Valorant DM: флики в реальных дуэлях", "ingame", 3,
                     "correction", "1 матч DM в день",
                     "Флик на звук/появление — доводка до головы без проскока под давлением."),
    ],
```

`rank_thresholds` не передаётся (=None: у Valorant нет счёта Voltaic).

- [ ] **Step 5: Меню по платформе**

Заменить `_tier1_core_drills`/`menu_drill_ids`/`menu_for_prompt`:

```python
def _tier1_drills(training_platform: Optional[str]) -> List[CatalogDrill]:
    """Tier-1 дриллы под платформу игрока (первый клип всегда tier 1).

    None схлопывается в "ingame" СОЗНАТЕЛЬНО (не промптовым дефолтом): Valorant
    есть у каждого, чей клип мы анализируем; KovaaK's — нет. Рекомендация
    тренажёра без владения невыполнима; in-game владельцу KovaaK's — лишь
    неоптимальна. KovaaK's появляется в меню только при явном "kovaaks"."""
    include_kovaaks = training_platform == "kovaaks"
    return [d for metric in CORE_METRICS for d in CATALOG[metric]
            if d.tier == 1 and (include_kovaaks or d.platform != "kovaaks")]


def menu_drill_ids(training_platform: Optional[str] = None) -> frozenset:
    """Допустимые drill_id первого клипа; гейтится валидатором механически."""
    return frozenset(cd.drill_id for cd in _tier1_drills(training_platform))


def menu_for_prompt(training_platform: Optional[str] = None) -> str:
    lines = ["Меню дриллов (выбирай drill_id ТОЛЬКО отсюда):"]
    for cd in _tier1_drills(training_platform):
        lines.append(f"- {cd.drill_id} (метрика {cd.metric}, платформа"
                     f" {cd.platform}): {cd.name}")
    return "\n".join(lines)
```

- [ ] **Step 6: Контекстное меню в валидаторе и промпте**

`coach/validate.py`, строка `menu_ids = menu_drill_ids()`:

```python
    menu_ids = menu_drill_ids((evidence.get("clip") or {}).get("training_platform"))
```

и текст ошибки «не из меню» дополнить: `f"...; первый клип — только tier-1 дриллы твоей платформы"`.

`coach/prompt.py`, в `build_user_text`: `parts.append(menu_for_prompt((report.get("clip") or {}).get("training_platform")))`.

- [ ] **Step 7: Прогнать + полный сьют** — PASS (существующий тест меню «ровно 4 tier-1» мог зашивать kovaaks-id — обновить его ожидания на новую семантику: без платформы kovaaks исключён)

- [ ] **Step 8: Commit**

```bash
git add engine/clip_context.py coach/drill_catalog.py coach/validate.py coach/prompt.py tests/
git commit -m "feat(coach): in-game ветка каталога + training_platform + контекстное меню по платформе"
```

---

### Task 8: Проброс `training_platform`: CLI → пайплайн → API → форма

**Files:**
- Modify: `aim_metrics.py` (арг + `_build_context`)
- Modify: `backend/services/analysis_pipeline.py` (`run_pipeline` параметр)
- Modify: `backend/main.py` (Form-поле + проброс)
- Modify: `frontend/src/api.js`, `frontend/src/components/UploadForm.js`
- Test: `tests/test_analysis_pipeline.py` (или соседний с тестами upload — `grep -l upload tests/`)

**Interfaces:**
- Consumes: `ClipContext.training_platform`, `context_for_video(..., training_platform=...)` (Task 7).
- Produces: `run_pipeline(..., training_platform: Optional[str] = None)`; API Form-поле `training_platform`; CLI `--training-platform {kovaaks,ingame}`.

- [ ] **Step 1: Падающий тест** — в файле тестов пайплайна (инжектируемый detector там уже есть; по образцу соседних):

```python
def test_training_platform_reaches_report_clip_block():
    # run_pipeline(..., training_platform="kovaaks") с фейковым детектором ->
    # result.evidence_report["clip"]["training_platform"] == "kovaaks"
    ...
```

И API-тест (файл тестов backend, TestClient уже используется):

```python
def test_upload_accepts_training_platform():
    # multipart c training_platform="ingame" -> 200; сессия создаётся
    ...
```

- [ ] **Step 2: Прогнать — падают** (unexpected keyword argument)

- [ ] **Step 3: Реализация**

`backend/services/analysis_pipeline.py`, `run_pipeline`: параметр `training_platform: Optional[str] = None` (после `map_name`), проброс в `context_for_video(..., training_platform=training_platform)`.

`backend/main.py`: в `upload_video` — `training_platform: str | None = Form(None)`; в `process_video_task` — параметр и проброс в `run_pipeline`; в `background_tasks.add_task(...)` — передать.

`aim_metrics.py`: после `parser.add_argument("--map", ...)`:

```python
    parser.add_argument("--training-platform", default=None,
                        choices=("kovaaks", "ingame"),
                        help="где игрок готов тренироваться (user-supplied)")
```

и в `_build_context` в `meta`: `training_platform=args.training_platform,`.

`frontend/src/api.js`: в `uploadClip({ ..., trainingPlatform })` — `if (trainingPlatform) form.append('training_platform', trainingPlatform);`.

`frontend/src/components/UploadForm.js`: состояние `const [trainingPlatform, setTrainingPlatform] = useState('');`, проброс `trainingPlatform: trainingPlatform` в onSubmit-объект, и селект рядом с полем «Агент» (стиль соседних полей):

```jsx
            <label htmlFor="training-platform">Тренировки</label>
            <select id="training-platform" value={trainingPlatform}
                    onChange={(e) => setTrainingPlatform(e.target.value)}>
              <option value="">не указано</option>
              <option value="ingame">в Valorant (Range/DM)</option>
              <option value="kovaaks">KovaaK's</option>
            </select>
```

(проверить, как App.js передаёт поля из UploadForm в `uploadClip`, и пробросить `trainingPlatform` по той же цепочке).

- [ ] **Step 4: Прогнать тесты пайплайна/бэкенда + полный сьют** — PASS

- [ ] **Step 5: Commit**

```bash
git add aim_metrics.py backend/services/analysis_pipeline.py backend/main.py frontend/src/api.js frontend/src/components/UploadForm.js tests/
git commit -m "feat(pipeline): проброс training_platform от CLI/API/формы до clip-блока отчёта"
```

---

### Task 9: Финальная верификация

- [ ] **Step 1:** `.\.venv\Scripts\python.exe -m pytest -q` — весь сьют зелёный (ожидаемо ~330+; ноль failed)
- [ ] **Step 2:** `cd frontend; npm run build` — сборка чистая (схема аддитивна, ReportView не трогали)
- [ ] **Step 3:** Смоук CLI на реальном клипе (gt-путь, без сети):

```
.\.venv\Scripts\python.exe aim_metrics.py --source gt --xml dataset1/clip2.xml --video dataset1/clip2.mp4 --player-id smoke --edpi 280 --training-platform ingame --episodes --placement --correction --report-json -
```

Глазами: в clip-блоке `cm_per_360` ≈ 46.65 и `training_platform: "ingame"`; у находок `severity_ratio`; у correction `flicks_sparse`/`flicks_jitter_n`/`flick_overshoot_cm_equiv_median`; `metrics_version: 3`, `schema_version: "1.3"`.

- [ ] **Step 4:** Коммит остатков (если были правки по смоуку), НЕ пушить (пуш вместе с решением по Фазе 4 — см. память проекта).

---

## Замечания для исполнителя

- **Sparse-флики не получают FlickPhase/вердикта вовсе** (счётчик, не флаг на записи): наблюдаемый контракт спеки — `flicks_sparse` в values и исключение из медиан/confidence; поле `sparse=True` на фазе было бы мёртвым грузом (YAGNI).
- **`_med` и jitter:** settle_time/overshoot/path у settled-флика None не бывают — их медианы фильтр не задевает; фильтр нужен ровно из-за jitter.
- **Тесты с «...»** (test_report/validate/pipeline): тела дописать по образцу соседних тестов того же файла — там уже есть фабрики evidence/эпизодов/клиентов; ключевые assert'ы указаны в каждом тесте комментарием.
- **Существующие тесты менять можно только там, где план это явно называет** (schema_version, меню tier-1); любой другой красный существующий тест — сигнал ошибки реализации, не повод править тест.
