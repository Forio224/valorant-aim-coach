# Фаза 2B: петля прогресса на engine-сигнале Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Замкнуть петлю прогресса на уже имеющемся engine-сигнале: движок считает кумулятивную дельту метрики от anchor'а неразрешённой серии, коуч честно озвучивает направление, механический guard запрещает выдуманное направление и каузальность. Без внешнего API (KovaaK's/Voltaic → 2C), без UI (§G → 2C), без миграции схемы.

**Architecture:** Числовое ядро критерия выносится в общий `engine/`-хелпер (нейтральный dict, анти-цикл `engine↔coach`), который зовут и `build_criterion` (Фаза 1), и новый `compute_drill_progress` (Фаза 2B). `drill_progress` — чистая функция движка над `findings` + инжектируемой поклиповой историей; кладёт top-level секцию в evidence-JSON. Coach получает структурное поле `progress_explained` (enum-direction), валидатор матчит его против движка и банит каузальность. Пайплайн — тупой добытчик истории через инжектируемый `history_provider`.

**Tech Stack:** Python 3, dataclasses/dict, `statistics`, pytest, Pydantic (coach schema), SQLModel (backend history read). Без новых зависимостей.

## Global Constraints

- Python только через `.\.venv\Scripts\python.exe` (каталог `venv\` сломан). Тесты: `.\.venv\Scripts\python.exe -m pytest -q`.
- **Управляющий принцип:** любое число в отчёте происходит из движка; VLM не производит чисел. 2B добавляет числа движка + guard против выдуманного направления/каузальности.
- **Анти-цикл (жёстко):** `engine/` НЕ импортирует `coach/`. Общий хелпер живёт в `engine/` и возвращает НЕЙТРАЛЬНЫЙ dict, НЕ `SuccessCriterion`. Подтверждено: сегодня ноль импортов `engine → coach`; `aim_metrics.py` (CLI) импортит только `engine`. Греп-гард — тест Task 1.
- **Старое поведение `build_criterion` НЕ меняется** — существующий `tests/test_drill_catalog.py` остаётся зелёным (рефактор чисто внутренний).
- **Единая нормировка + точность:** `normalize(value_key, raw)` применяет ТОТ ЖЕ per-`value_key` трансформ, что `compute_metric_criterion` кладёт в `baseline`, ВКЛЮЧАЯ округление (`_r` до 3 знаков для HU; `int` для счётчиков; `abs` для `*_bias_hu`). `delta = _r(current − anchor)` до baseline-точности, НЕ голый `round()` до целого. anchor и current — в идентичном пространстве.
- **Кумулятивный anchor:** anchor = первый флаг текущей *неразрешённой* серии; серию рвёт только резолюция (value удовлетворил `target` при confidence `≥ hypothesis`), НЕ отсутствие дрилла. **correction** (`target=None`) — единый anchor, не рвётся никогда.
- **confidence дельты = `min(anchor_conf, current_conf)`** по порядку `insufficient < hypothesis < diagnosis`.
- **`drill_progress` — ретроспективный:** репортим метрику с открытой серией в истории; первый клип / нет серии → запись не эмитится; `baseline_set` НЕ вводим.
- **Каузальность — никогда:** новый стопворд-класс банится ЯВНО на `summary` + `caveats` + `progress_explained.explanation` + `drill.rationale` + `findings_explained.explanation`. Предпочитать over-block под-block.
- **Границы:** НЕ трогаем фронт, каталог сценариев, тир-прогрессию, `settle_jitter`-триггер, KovaaK's API, поле «дата съёмки». `order_uncertain` = константа `True`. `build_report` получает `drill_history: Sequence = ()` (аддитивный дефолт; CLI подаёт `[]`).
- Язык кода/комментариев — как в окружении (русскоязычные докстроки, английские идентификаторы).
- Спека: `docs/superpowers/specs/2026-07-07-phase2b-progress-loop-design.md`.

---

### Task 1: Общий хелпер критерия (`engine/metrics/criterion.py`) + рефактор `build_criterion`

**Files:**
- Create: `engine/metrics/criterion.py`
- Modify: `coach/drill_catalog.py` (`build_criterion` → тонкая обёртка; импорт хелпера; убрать дублированные константы/`_r`/`CORE_METRICS`)
- Test: `tests/test_criterion_helper.py` (новый), `tests/test_drill_catalog.py` (регрессия — не менять, должен остаться зелёным)

**Interfaces:**
- Produces:
  - `engine.metrics.criterion.CORE_METRICS: tuple`
  - `compute_metric_criterion(metric: str, values: dict) -> dict` — `{value_key, comparator, target, baseline, directional_meaningful}`. `baseline` — в baseline-space (нормировано). `comparator ∈ {"<","count_le","direction"}`. `directional_meaningful=False` для вырожденца correction (`count==0`) и для «нет данных».
  - `normalize(value_key: str, raw: Optional[float]) -> Optional[float]`
  - `PLACEMENT_TARGET_FRACTION`, `CONSISTENCY_IMPROVEMENT`, `BIAS_HALVE_FACTOR` (перенесены из `drill_catalog`).
- Consumes (Task 2/4): `compute_metric_criterion`, `normalize`, `CORE_METRICS`.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_criterion_helper.py`:

```python
# -*- coding: utf-8 -*-
"""Общий хелпер критерия (Фаза 2B): нейтральный dict + единая нормировка."""
from engine.metrics.criterion import (compute_metric_criterion, normalize,
                                       CORE_METRICS)


def test_core_metrics_order():
    assert CORE_METRICS == ("placement", "consistency", "bias", "correction")


def test_consistency_neutral_dict():
    m = compute_metric_criterion("consistency", {"mae_hu": 5.0})
    assert m == {"value_key": "mae_hu", "comparator": "<", "target": 4.25,
                 "baseline": 5.0, "directional_meaningful": True}


def test_bias_baseline_is_abs_rounded():
    m = compute_metric_criterion("bias", {"y_bias_hu": -0.6})
    assert m["value_key"] == "y_bias_hu" and m["comparator"] == "<"
    assert m["baseline"] == 0.6 and m["target"] == 0.3
    assert m["directional_meaningful"] is True


def test_placement_target_and_int_baseline():
    m = compute_metric_criterion("placement", {"total": 10, "below": 7})
    assert m["value_key"] == "below" and m["comparator"] == "count_le"
    assert m["target"] == 2.0 and m["baseline"] == 7.0


def test_correction_picks_worst_axis():
    m = compute_metric_criterion(
        "correction", {"x_overshoots": 1, "x_undershoots": 0,
                       "y_overshoots": 3, "y_undershoots": 0,
                       "flicks_analysed": 5})
    assert m["value_key"] == "y_overshoots" and m["comparator"] == "direction"
    assert m["target"] is None and m["baseline"] == 3.0
    assert m["directional_meaningful"] is True


def test_correction_degenerate_count_zero():
    m = compute_metric_criterion(
        "correction", {"x_overshoots": 0, "x_undershoots": 0,
                       "y_overshoots": 0, "y_undershoots": 0,
                       "flicks_analysed": 4})
    assert m["value_key"] == "flicks_analysed" and m["baseline"] == 0.0
    assert m["directional_meaningful"] is False


def test_missing_data_marks_not_meaningful():
    m = compute_metric_criterion("consistency", {})
    assert m["baseline"] is None and m["directional_meaningful"] is False


def test_normalize_bias_abs_and_round():
    assert normalize("y_bias_hu", -0.6001) == 0.6
    assert normalize("mae_hu", 4.2506) == 4.251
    assert normalize("below", 7.0) == 7
    assert normalize("x_overshoots", 3.0) == 3
    assert normalize("mae_hu", None) is None
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_criterion_helper.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.metrics.criterion'`.

- [ ] **Step 3: Написать `engine/metrics/criterion.py`**

```python
# -*- coding: utf-8 -*-
"""Числовое ядро критерия успеха — общий слой Фазы 1 (build_criterion) и
Фазы 2B (compute_drill_progress).

Живёт в engine/ и возвращает НЕЙТРАЛЬНЫЙ dict, НЕ SuccessCriterion:
coach.schema не импортируется движком (иначе цикл coach.drill_catalog →
engine → coach.schema и инверсия слоёв — движок автономен под CLI
aim_metrics.py). build_criterion (coach/) оборачивает dict в SuccessCriterion
+ человеческий text. normalize держит anchor и current в одном baseline-space.
"""
from typing import Optional

CORE_METRICS = ("placement", "consistency", "bias", "correction")

PLACEMENT_TARGET_FRACTION = 0.2
CONSISTENCY_IMPROVEMENT = 0.15     # MAE < base * 0.85
BIAS_HALVE_FACTOR = 0.5

_COUNT_KEYS = ("below", "x_overshoots", "x_undershoots",
               "y_overshoots", "y_undershoots", "flicks_analysed")


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    return None if x is None else round(x, digits)


def normalize(value_key: str, raw: Optional[float]) -> Optional[float]:
    """Сырое значение метрики → baseline-space по value_key. ТОТ ЖЕ трансформ,
    что compute_metric_criterion кладёт в baseline (вкл. округление)."""
    if raw is None:
        return None
    if value_key.endswith("_bias_hu"):
        return _r(abs(raw))
    if value_key in _COUNT_KEYS:
        return int(round(raw))
    return _r(raw)


def compute_metric_criterion(metric: str, values: dict) -> dict:
    """Нейтральный dict {value_key, comparator, target, baseline,
    directional_meaningful}. directional_meaningful=False = дельту по критерию
    считать нельзя (нет данных / вырожденец correction)."""
    if metric == "placement":
        total, below = values.get("total"), values.get("below")
        if total is None or below is None:
            return {"value_key": "below", "comparator": "count_le",
                    "target": None, "baseline": None,
                    "directional_meaningful": False}
        return {"value_key": "below", "comparator": "count_le",
                "target": float(round(PLACEMENT_TARGET_FRACTION * total)),
                "baseline": float(int(below)), "directional_meaningful": True}
    if metric == "consistency":
        base = values.get("mae_hu")
        if base is None:
            return {"value_key": "mae_hu", "comparator": "<", "target": None,
                    "baseline": None, "directional_meaningful": False}
        return {"value_key": "mae_hu", "comparator": "<",
                "target": _r(base * (1 - CONSISTENCY_IMPROVEMENT)),
                "baseline": _r(base), "directional_meaningful": True}
    if metric == "bias":
        raw = values.get("y_bias_hu")
        if raw is None:
            return {"value_key": "y_bias_hu", "comparator": "<", "target": None,
                    "baseline": None, "directional_meaningful": False}
        base = abs(raw)
        return {"value_key": "y_bias_hu", "comparator": "<",
                "target": _r(base * BIAS_HALVE_FACTOR), "baseline": _r(base),
                "directional_meaningful": True}
    if metric == "correction":
        pairs = [("x_overshoots", values.get("x_overshoots", 0)),
                 ("x_undershoots", values.get("x_undershoots", 0)),
                 ("y_overshoots", values.get("y_overshoots", 0)),
                 ("y_undershoots", values.get("y_undershoots", 0))]
        value_key, count = max(pairs, key=lambda p: p[1])
        if count == 0:
            value_key = "flicks_analysed"
        return {"value_key": value_key, "comparator": "direction",
                "target": None, "baseline": float(count),
                "directional_meaningful": count > 0}
    raise ValueError(f"неизвестная метрика критерия: {metric}")
```

- [ ] **Step 4: Запустить тест хелпера — зелёный**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_criterion_helper.py -q`
Expected: PASS.

- [ ] **Step 5: Рефактор `build_criterion` в `coach/drill_catalog.py`**

В `coach/drill_catalog.py`: (1) заменить импорт-блок и убрать локальные константы `PLACEMENT_TARGET_FRACTION`/`CONSISTENCY_IMPROVEMENT`/`BIAS_HALVE_FACTOR` (строки ~19-21), локальный `CORE_METRICS` (строка ~16) и локальный `_r` (строки ~142-143); (2) заменить тело `build_criterion` (строки ~146-206) на обёртку над хелпером.

Импорт вверху файла (рядом с `from coach.schema import ...`):
```python
from engine.metrics.criterion import (CORE_METRICS, CONSISTENCY_IMPROVEMENT,
                                       compute_metric_criterion)
```

Новое тело `build_criterion` (текст строится здесь; числа — из хелпера):
```python
def build_criterion(metric: str, values: dict) -> SuccessCriterion:
    """Детерминированный критерий: числа из общего хелпера движка (engine/),
    человеческий text — здесь."""
    m = compute_metric_criterion(metric, values)
    vk, comparator = m["value_key"], m["comparator"]
    target, baseline = m["target"], m["baseline"]
    if metric == "placement":
        if baseline is None:
            text = "Нужен ещё клип для числового критерия пре-айма."
        else:
            text = (f"Довести число появлений с прицелом ниже линии головы до "
                    f"≤ {int(target)} из {values['total']} (сейчас {int(baseline)}); "
                    f"средний вертикальный промах — к нулю.")
    elif metric == "consistency":
        if baseline is None:
            text = "Нужен ещё клип для числового критерия точности."
        else:
            text = (f"Средняя ошибка в дуэли < {target} HU "
                    f"(−{int(CONSISTENCY_IMPROVEMENT * 100)}% к текущим "
                    f"{baseline} HU) на следующем клипе.")
    elif metric == "bias":
        if baseline is None:
            text = "Нужен ещё клип для числового критерия смещения."
        else:
            text = (f"Систематическое вертикальное смещение |Y| < {target} HU "
                    f"(вдвое меньше текущих {baseline} HU).")
    elif metric == "correction":
        if not m["directional_meaningful"]:
            text = ("Держать чистые флики без перелёта и недолёта на следующем "
                    "клипе.")
        else:
            count = int(baseline)
            analysed = values.get("flicks_analysed", 0)
            axis = vk[0].upper()
            kind = "перелёт" if "overshoots" in vk else "недолёт"
            text = (f"Снизить долю {kind}ов по оси {axis}: сейчас {count} из "
                    f"{analysed} фликов — двигать в сторону чистых фликов "
                    f"(прокси-метрика, без жёсткого порога).")
    else:
        raise ValueError(f"неизвестная метрика критерия: {metric}")
    return SuccessCriterion(metric=metric, value_key=vk, comparator=comparator,
                            target=target, baseline=baseline, text=text)
```

> Заметка: `_tier1_core_drills` использует `CORE_METRICS` — теперь импортируется из `engine.metrics.criterion`, работает без изменений. Проверить, что удаление локального `_r` не осиротило других вызовов (грепнуть `_r(` в `drill_catalog.py` — если остались, вернуть локальный `_r` или импортировать `from engine.metrics.criterion import _r`).

- [ ] **Step 6: Регрессия `build_criterion` + агримент-тест + греп-гард**

Дописать в `tests/test_criterion_helper.py`:
```python
def test_build_criterion_agrees_with_helper():
    """build_criterion берёт числа из того же хелпера (single source)."""
    from coach.drill_catalog import build_criterion
    values = {"mae_hu": 5.0}
    m = compute_metric_criterion("consistency", values)
    sc = build_criterion("consistency", values)
    assert sc.value_key == m["value_key"] and sc.comparator == m["comparator"]
    assert sc.target == m["target"] and sc.baseline == m["baseline"]


def test_engine_does_not_import_coach():
    """Анти-цикл: ни один модуль engine/ не импортирует coach/."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parent.parent / "engine"
    offenders = [p.name for p in root.rglob("*.py")
                 if re.search(r"^\s*(from|import)\s+coach",
                              p.read_text(encoding="utf-8"), re.MULTILINE)]
    assert offenders == [], f"engine → coach импорт запрещён: {offenders}"
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_criterion_helper.py tests/test_drill_catalog.py -q`
Expected: PASS (весь `test_drill_catalog.py` зелёный — поведение `build_criterion` не изменилось; агримент и греп-гард зелёные).

- [ ] **Step 7: Commit**

```bash
git add engine/metrics/criterion.py coach/drill_catalog.py tests/test_criterion_helper.py
git commit -m "refactor(engine): общий хелпер критерия (нейтральный dict, анти-цикл); build_criterion — обёртка"
```

---

### Task 2: `compute_drill_progress` (`engine/metrics/drill_progress.py`) + встройка в `build_report`

**Files:**
- Create: `engine/metrics/drill_progress.py`
- Modify: `engine/report.py` (импорт; `build_report` получает `drill_history` и кладёт `report["drill_progress"]`)
- Test: `tests/test_drill_progress.py` (новый)

**Interfaces:**
- Consumes: `engine.metrics.criterion.{CORE_METRICS, compute_metric_criterion, normalize}`.
- Produces:
  - `compute_drill_progress(findings: Sequence[dict], drill_history: Sequence[dict]) -> List[dict]`.
    `ClipSnapshot = {clip_time, clip_id, assignments:{metric:drill_id}, findings:{metric:{values, confidence}}}`.
    Запись: `{metric, drill_id, value_key, comparator, anchor_value, anchor_clip_id, current_value, delta, direction, confidence, series_len, resolved_now, order_uncertain}`. `direction ∈ {"improved","regressed","flat","insufficient"}`.
  - `build_report(..., drill_history: Sequence = ())` → `report["drill_progress"]`.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_drill_progress.py`:

```python
# -*- coding: utf-8 -*-
"""Петля прогресса на engine-сигнале (Фаза 2B) — синтетика, без БД."""
from engine.metrics.drill_progress import compute_drill_progress


def _finding(metric, values, confidence="diagnosis"):
    return {"metric": metric, "values": values, "confidence": confidence}


def _snap(clip_time, clip_id, assignments, findings):
    return {"clip_time": clip_time, "clip_id": clip_id,
            "assignments": assignments, "findings": findings}


def _mae_snap(t, cid, mae, conf="diagnosis", flagged=True):
    return _snap(t, cid, {"consistency": "consistency_t1_vt_ww5t_novice"} if flagged
                else {}, {"consistency": _finding("consistency", {"mae_hu": mae}, conf)})


# ---- ретроспективная пустота -------------------------------------------------

def test_first_clip_no_history_empty():
    findings = [_finding("consistency", {"mae_hu": 5.0})]
    assert compute_drill_progress(findings, []) == []


def test_metric_never_flagged_not_reported():
    # история есть, но consistency ни разу не флагнута → не репортим
    history = [_snap(1, "c1", {}, {"consistency": _finding("consistency", {"mae_hu": 5.0})})]
    findings = [_finding("consistency", {"mae_hu": 4.0})]
    assert compute_drill_progress(findings, history) == []


# ---- кумулятивная дельта (не clip-to-clip) -----------------------------------

def test_cumulative_delta_from_series_anchor():
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.6),
               _mae_snap(3, "c3", 4.4)]
    findings = [_finding("consistency", {"mae_hu": 4.2})]   # текущий клип
    rec = compute_drill_progress(findings, history)[0]
    assert rec["anchor_clip_id"] == "c1" and rec["anchor_value"] == 5.0
    assert rec["current_value"] == 4.2
    assert rec["delta"] == -0.8              # 4.2 − 5.0, кумулятив, НЕ −0.2
    assert rec["direction"] == "improved"
    assert rec["series_len"] == 3
    assert rec["order_uncertain"] is True
    assert rec["drill_id"] == "consistency_t1_vt_ww5t_novice"


# ---- отсутствие дрилла НЕ рвёт серию (Баг A) ---------------------------------

def test_drill_absence_does_not_break_series():
    # clip2 не флагнут (топ-2-трим), но слабость не разрешена → anchor держится
    history = [_mae_snap(1, "c1", 5.0),
               _mae_snap(2, "c2", 4.9, flagged=False),
               _mae_snap(3, "c3", 4.8)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.7})], history)[0]
    assert rec["anchor_clip_id"] == "c1" and rec["delta"] == -0.3


# ---- разрыв по резолюции + новый anchor ---------------------------------------

def test_resolution_breaks_series_and_reanchors():
    # target на c1 = 5.0*0.85 = 4.25; c2 mae 4.0 < 4.25 → резолюция; c3 рефлаг
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.0),
               _mae_snap(3, "c3", 6.0)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 5.5})], history)[0]
    assert rec["anchor_clip_id"] == "c3" and rec["anchor_value"] == 6.0
    assert rec["delta"] == -0.5 and rec["direction"] == "improved"


def test_resolved_then_not_reflagged_drops_out():
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.0, flagged=False)]
    # разрешено на c2, дальше не флагнута → нет открытой серии
    assert compute_drill_progress([_finding("consistency", {"mae_hu": 3.9})], history) == []


def test_resolution_requires_at_least_hypothesis():
    # c2 под target, но insufficient → НЕ резолюция, серия держит anchor c1
    history = [_mae_snap(1, "c1", 5.0), _mae_snap(2, "c2", 4.0, conf="insufficient"),
               _mae_snap(3, "c3", 4.5)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.4})], history)[0]
    assert rec["anchor_clip_id"] == "c1"


# ---- resolved_now ------------------------------------------------------------

def test_resolved_now_flag_on_current_clip():
    history = [_mae_snap(1, "c1", 5.0)]      # target 4.25
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.0})], history)[0]
    assert rec["resolved_now"] is True and rec["direction"] == "improved"


def test_under_target_but_insufficient_not_resolved_now():
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": 4.0}, "insufficient")], history)[0]
    assert rec["resolved_now"] is False and rec["confidence"] == "insufficient"


# ---- min-confidence ----------------------------------------------------------

def test_confidence_is_min_of_endpoints():
    history = [_mae_snap(1, "c1", 5.0, conf="hypothesis")]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": 4.8}, "diagnosis")], history)[0]
    assert rec["confidence"] == "hypothesis"     # min(hypothesis, diagnosis)


# ---- bias-abs ----------------------------------------------------------------

def test_bias_normalized_by_magnitude():
    def bsnap(t, cid, yb, conf="diagnosis"):
        return _snap(t, cid, {"bias": "bias_t1_vt_1w4ts_novice"},
                     {"bias": _finding("bias", {"y_bias_hu": yb}, conf)})
    history = [bsnap(1, "c1", -0.6)]        # baseline abs = 0.6
    # текущий +0.5 → |0.5| < 0.6 → improved (не «улучшение» из-за смены знака)
    rec = compute_drill_progress(
        [_finding("bias", {"y_bias_hu": 0.5})], history)[0]
    assert rec["anchor_value"] == 0.6 and rec["current_value"] == 0.5
    assert rec["direction"] == "improved" and rec["delta"] == -0.1


# ---- null current ------------------------------------------------------------

def test_null_current_value_insufficient():
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": None}, "insufficient")], history)[0]
    assert rec["delta"] is None and rec["direction"] == "insufficient"
    assert rec["confidence"] == "insufficient"


# ---- correction: единый anchor, вырожденец → skip ----------------------------

def _corr_snap(t, cid, vals, conf="diagnosis", flagged=True):
    return _snap(t, cid, {"correction": "correction_t1_vt_pasu_novice"} if flagged
                else {}, {"correction": _finding("correction", vals, conf)})


def test_correction_single_anchor_never_breaks():
    v = lambda xo: {"x_overshoots": xo, "x_undershoots": 0, "y_overshoots": 0,
                    "y_undershoots": 0, "flicks_analysed": 5}
    history = [_corr_snap(1, "c1", v(3)), _corr_snap(2, "c2", v(0)),   # count 0 не рвёт
               _corr_snap(3, "c3", v(2))]
    rec = compute_drill_progress([_finding("correction", v(1))], history)[0]
    assert rec["anchor_clip_id"] == "c1" and rec["anchor_value"] == 3.0
    assert rec["current_value"] == 1 and rec["delta"] == -2 and rec["direction"] == "improved"
    assert rec["resolved_now"] is False       # target=None у прокси


def test_correction_degenerate_anchor_skipped_as_insufficient():
    v0 = {"x_overshoots": 0, "x_undershoots": 0, "y_overshoots": 0,
          "y_undershoots": 0, "flicks_analysed": 4}
    history = [_corr_snap(1, "c1", v0)]        # anchor вырожден (count 0)
    rec = compute_drill_progress([_finding("correction", v0)], history)[0]
    assert rec["direction"] == "insufficient" and rec["delta"] is None


# ---- граница округления/точности ---------------------------------------------

def test_sub_hu_delta_not_collapsed_to_flat():
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress([_finding("consistency", {"mae_hu": 4.8})], history)[0]
    assert rec["delta"] == -0.2 and rec["direction"] == "improved"   # НЕ 0/flat


def test_current_exactly_on_target_stable_resolution():
    # anchor mae 5.0 → target 4.25; current ровно 4.25 при сырой «шумной» точности
    history = [_mae_snap(1, "c1", 5.0)]
    rec = compute_drill_progress(
        [_finding("consistency", {"mae_hu": 4.2500001})], history)[0]
    assert rec["current_value"] == 4.25          # нормировано в одно пространство
    assert rec["resolved_now"] is False          # 4.25 < 4.25 ложно (строгий <)


# ---- детерминированный порядок -----------------------------------------------

def test_records_sorted_by_core_metrics_order():
    history = [
        _snap(1, "c1", {"correction": "correction_t1_vt_pasu_novice",
                        "consistency": "consistency_t1_vt_ww5t_novice"},
              {"correction": _finding("correction",
                   {"x_overshoots": 2, "x_undershoots": 0, "y_overshoots": 0,
                    "y_undershoots": 0, "flicks_analysed": 5}),
               "consistency": _finding("consistency", {"mae_hu": 5.0})}),
    ]
    findings = [_finding("correction",
                    {"x_overshoots": 1, "x_undershoots": 0, "y_overshoots": 0,
                     "y_undershoots": 0, "flicks_analysed": 5}),
                _finding("consistency", {"mae_hu": 4.8})]
    recs = compute_drill_progress(findings, history)
    assert [r["metric"] for r in recs] == ["consistency", "correction"]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_drill_progress.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.metrics.drill_progress'`.

- [ ] **Step 3: Написать `engine/metrics/drill_progress.py`**

```python
# -*- coding: utf-8 -*-
"""Stage 7 (Фаза 2B): петля прогресса на engine-сигнале.

Отвечает на «сдвинулась ли метрика после совета?»: кумулятивная дельта от
anchor'а (первый флаг неразрешённой серии) к текущему клипу. Разрыв серии —
по резолюции метрики (value достиг target при confidence ≥ hypothesis), НЕ по
отсутствию дрилла (топ-2-трим/невыбор VLM не сбрасывают anchor). correction
(target-less прокси) — единый anchor, не рвётся. confidence = min(anchor,
current). Числа считает движок; каузальности нет — только дельта+направление.
"""
from typing import List, Optional, Sequence

from engine.metrics.criterion import (CORE_METRICS, compute_metric_criterion,
                                       normalize)

_CONF_ORDER = {"insufficient": 0, "hypothesis": 1, "diagnosis": 2}


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    return None if x is None else round(x, digits)


def _min_conf(a: str, b: str) -> str:
    return a if _CONF_ORDER[a] <= _CONF_ORDER[b] else b


def _meets(comparator: str, target: Optional[float], value: Optional[float],
           conf: str) -> bool:
    """Резолюция: value удовлетворил target при доверяемой confidence."""
    if target is None or value is None or conf == "insufficient":
        return False
    if comparator == "<":
        return value < target
    if comparator == "count_le":
        return value <= target
    return False                       # direction: порога нет


def _open_series_anchor(metric: str, history: Sequence[dict]) -> Optional[dict]:
    """anchor текущей неразрешённой серии, либо None (не флагнута / разрешена и
    не рефлагнута). Разрыв — по резолюции, не по отсутствию дрилла."""
    flagged = [s for s in history
               if metric in s.get("assignments", {}) and metric in s["findings"]]
    if not flagged:
        return None
    anchor = flagged[0]
    while True:
        m = compute_metric_criterion(metric, anchor["findings"][metric]["values"])
        target, comparator, value_key = m["target"], m["comparator"], m["value_key"]
        if target is None:             # correction: единый anchor, не рвётся
            return anchor
        resolved = None
        for s in history:
            if s["clip_time"] <= anchor["clip_time"]:
                continue
            f = s["findings"].get(metric)
            if f is None or f["confidence"] == "insufficient":
                continue
            val = normalize(value_key, f["values"].get(value_key))
            if _meets(comparator, target, val, f["confidence"]):
                resolved = s
                break
        if resolved is None:
            return anchor
        nxt = next((s for s in flagged
                    if s["clip_time"] > resolved["clip_time"]), None)
        if nxt is None:
            return None
        anchor = nxt


def compute_drill_progress(findings: Sequence[dict],
                           drill_history: Sequence[dict]) -> List[dict]:
    """Записи прогресса по метрикам с открытой серией (порядок CORE_METRICS)."""
    history = sorted(drill_history, key=lambda s: s["clip_time"])
    findings_by_metric = {f["metric"]: f for f in findings}
    records: List[dict] = []
    for metric in CORE_METRICS:
        anchor = _open_series_anchor(metric, history)
        if anchor is None:
            continue
        m = compute_metric_criterion(metric, anchor["findings"][metric]["values"])
        value_key, comparator, target = m["value_key"], m["comparator"], m["target"]
        anchor_conf = anchor["findings"][metric]["confidence"]
        anchor_value = m["baseline"] if m["directional_meaningful"] else None

        cur = findings_by_metric.get(metric)
        current_conf = cur["confidence"] if cur else "insufficient"
        current_value = (normalize(value_key, cur["values"].get(value_key))
                         if cur else None)

        if anchor_value is None or current_value is None:
            delta, direction, confidence, resolved_now = (
                None, "insufficient", "insufficient", False)
        else:
            delta = _r(current_value - anchor_value)
            direction = ("flat" if delta == 0
                         else "improved" if current_value < anchor_value
                         else "regressed")
            confidence = _min_conf(anchor_conf, current_conf)
            resolved_now = _meets(comparator, target, current_value, current_conf)

        drill_id = next((s["assignments"][metric] for s in reversed(history)
                         if metric in s.get("assignments", {})), None)
        series_len = sum(1 for s in history
                         if s["clip_time"] >= anchor["clip_time"]
                         and metric in s["findings"])
        records.append({
            "metric": metric, "drill_id": drill_id, "value_key": value_key,
            "comparator": comparator, "anchor_value": anchor_value,
            "anchor_clip_id": anchor["clip_id"], "current_value": current_value,
            "delta": delta, "direction": direction, "confidence": confidence,
            "series_len": series_len, "resolved_now": resolved_now,
            "order_uncertain": True,
        })
    return records
```

- [ ] **Step 4: Запустить тест — зелёный**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_drill_progress.py -q`
Expected: PASS (все случаи edge-матрицы).

- [ ] **Step 5: Встроить в `build_report` (`engine/report.py`)**

Добавить импорт рядом с другими `from engine.metrics...`:
```python
from engine.metrics.drill_progress import compute_drill_progress
```
Изменить сигнатуру `build_report` (добавить `drill_history`) и после сборки `report` (перед `if profile is not None:`) вписать секцию:
```python
def build_report(ctx: ClipContext, samples: Sequence[FrameSample],
                 episodes: Sequence[Episode],
                 duel_hu: float = DEFAULT_DUEL_HU,
                 profile: Optional[PlayerProfile] = None,
                 drill_history: Sequence = ()) -> dict:
    ...
    report = {
        ...
        "findings": [ ... ],
    }
    report["drill_progress"] = compute_drill_progress(report["findings"],
                                                      list(drill_history))
    if profile is not None:
        report["profile"] = asdict(profile)
    return report
```

- [ ] **Step 6: Тест встройки в отчёт**

Дописать в `tests/test_drill_progress.py`:
```python
def test_build_report_emits_drill_progress_key():
    from engine.clip_context import ClipContext
    from engine.report import build_report
    ctx = ClipContext(player_id="p", clip_id="cur", fps=60.0,
                      width=1920, height=1080, frame_count=100)
    report = build_report(ctx, [], [])          # пустой клип, без истории
    assert report["drill_progress"] == []       # ключ есть, дефолт пустой
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_drill_progress.py tests/test_report.py -q`
Expected: `test_drill_progress.py` зелёный; `test_report.py::test_report_on_real_clip_is_fully_evidenced` — pre-existing `FileNotFoundError` (нет `dataset1/`), НЕ регрессия.

- [ ] **Step 7: Commit**

```bash
git add engine/metrics/drill_progress.py engine/report.py tests/test_drill_progress.py
git commit -m "feat(engine): drill_progress — кумулятивная дельта, разрыв по резолюции, min-confidence"
```

---

### Task 3: Структурное поле прогресса коуча (`coach/schema.py`) + правило промпта

**Files:**
- Modify: `coach/schema.py` (`ProgressExplained` + `CoachReport.progress_explained`)
- Modify: `coach/prompt.py` (правило про `drill_progress`)
- Test: `tests/test_coach_schema.py` (дополнить), `tests/test_coach_prompt.py` (дополнить)

**Interfaces:**
- Produces: `coach.schema.ProgressExplained{metric:str, direction:Literal["improved","regressed","flat"], confidence:Confidence, explanation:str}`; `CoachReport.progress_explained: List[ProgressExplained]` (дефолт `[]`).
- Consumes (Task 4): `coach.progress_explained`.

- [ ] **Step 1: Написать падающий тест схемы**

Дописать в `tests/test_coach_schema.py`:
```python
def test_progress_explained_field_defaults_empty():
    from coach.schema import CoachReport, ProgressExplained
    r = CoachReport(summary="s", findings_explained=[], drills=[], caveats=[])
    assert r.progress_explained == []
    pe = ProgressExplained(metric="consistency", direction="improved",
                           confidence="hypothesis", explanation="движется в нужную сторону")
    r2 = CoachReport(summary="s", findings_explained=[], drills=[], caveats=[],
                     progress_explained=[pe])
    assert r2.progress_explained[0].direction == "improved"


def test_progress_direction_is_constrained_enum():
    import pytest
    from pydantic import ValidationError
    from coach.schema import ProgressExplained
    with pytest.raises(ValidationError):
        ProgressExplained(metric="bias", direction="insufficient",   # не в enum
                          confidence="hypothesis", explanation="x")
```

- [ ] **Step 2: Запустить — падает**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'ProgressExplained'`.

- [ ] **Step 3: Добавить схему (`coach/schema.py`)**

После класса `FindingExplained` добавить:
```python
class ProgressExplained(BaseModel):
    """Объяснение динамики одной метрики. direction — enum, матчится валидатором
    == engine.direction; человеческая формулировка — в explanation."""

    metric: str
    direction: Literal["improved", "regressed", "flat"]
    confidence: Confidence
    explanation: str
```
В `CoachReport` добавить поле (после `drills`):
```python
    progress_explained: List[ProgressExplained] = []
```
Обновить докстроку `CoachReport`: «progress_explained — динамика метрик по истории (Фаза 2B), заземляется валидатором против engine drill_progress».

- [ ] **Step 4: Тест промпта**

Дописать в `tests/test_coach_prompt.py`:
```python
def test_system_prompt_has_progress_rule():
    from coach.prompt import SYSTEM_PROMPT
    assert "drill_progress" in SYSTEM_PROMPT
    assert "progress_explained" in SYSTEM_PROMPT
    # запрет каузальности проговорён
    assert "сработал" in SYSTEM_PROMPT or "каузальн" in SYSTEM_PROMPT.lower()
```

- [ ] **Step 5: Добавить правило в промпт (`coach/prompt.py`)**

В `SYSTEM_PROMPT` добавить пункт 9 (перед закрывающими `"""` и блоком ТРЕНИРОВОЧНЫЙ ПЛАН — либо в конец правил groundedness):
```
9. ДИНАМИКА (если в evidence-JSON есть секция drill_progress): для каждой записи \
с direction из {improved, regressed, flat} добавь элемент в progress_explained: \
metric, direction (СКОПИРУЙ из drill_progress без изменений), confidence (СКОПИРУЙ \
из той же записи drill_progress — НЕ из finding), explanation. В explanation опиши \
направление человеческим языком («метрика движется в нужную сторону», «вернулась к \
прошлому уровню»); числа дельты — только из drill_progress. ЗАПРЕЩЕНО каузально \
связывать движение с дриллом («дрилл сработал», «благодаря тренировке», «из-за \
упражнения») — адхеренс и конфаундеры неизвестны, ты видишь только числа. Записи с \
direction="insufficient" в progress_explained НЕ добавляй — при желании упомяни «рано \
судить» в caveats без утверждения направления.
```

- [ ] **Step 6: Запустить тесты схемы и промпта — зелёные**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_schema.py tests/test_coach_prompt.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add coach/schema.py coach/prompt.py tests/test_coach_schema.py tests/test_coach_prompt.py
git commit -m "feat(coach): структурное progress_explained + правило динамики в промпте"
```

---

### Task 4: Guard валидатора (`coach/validate.py`) — заземление дельты, направления, запрет каузальности

**Files:**
- Modify: `coach/validate.py` (пул чисел += drill_progress; каузальный стопворд-класс на 5 локаций; блок валидации `progress_explained`)
- Test: `tests/test_coach_validate.py` (дополнить)

**Interfaces:**
- Consumes: `evidence["drill_progress"]` (Task 2), `coach.progress_explained` (Task 3).
- Produces: `validate_coach_report` дополнительно ловит: ungrounded/выдуманную дельту, `progress_explained.direction ≠ engine`, `confidence` не из `drill_progress`, метрику вне `drill_progress`, каузальную атрибуцию в `summary`/`caveats`/`progress.explanation`/`rationale`/`findings_explained`, hedged+утвердительное в progress.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_coach_validate.py` (использует существующий паттерн файла — сверься с его хелперами построения evidence/CoachReport; ниже самодостаточные фикстуры):
```python
def _evidence_with_progress(direction="improved", confidence="hypothesis"):
    return {
        "episodes": [], "findings": [
            {"metric": "consistency", "values": {"mae_hu": 4.8},
             "confidence": "diagnosis", "statement": "", "evidence": []}],
        "drill_progress": [{
            "metric": "consistency", "drill_id": "consistency_t1_vt_ww5t_novice",
            "value_key": "mae_hu", "comparator": "<", "anchor_value": 5.0,
            "anchor_clip_id": "c1", "current_value": 4.8, "delta": -0.2,
            "direction": direction, "confidence": confidence, "series_len": 2,
            "resolved_now": False, "order_uncertain": True}],
    }


def _coach_with_progress(direction="improved", confidence="hypothesis",
                         explanation="точность движется в нужную сторону"):
    from coach.schema import CoachReport, ProgressExplained
    return CoachReport(
        summary="Портрет без чисел.", findings_explained=[], drills=[], caveats=[],
        progress_explained=[ProgressExplained(
            metric="consistency", direction=direction, confidence=confidence,
            explanation=explanation)])


def test_valid_progress_passes():
    from coach.validate import validate_coach_report
    assert validate_coach_report(_coach_with_progress(),
                                 _evidence_with_progress()) == []


def test_grounded_delta_number_passes():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(explanation="ошибка снизилась на 0.2 HU")
    assert validate_coach_report(coach, _evidence_with_progress()) == []


def test_invented_delta_number_rejected():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(explanation="ошибка снизилась на 9.9 HU")
    errors = validate_coach_report(coach, _evidence_with_progress())
    assert any("9.9" in e for e in errors)


def test_direction_mismatch_rejected():
    from coach.validate import validate_coach_report
    # движок сказал improved, коуч заявил regressed
    coach = _coach_with_progress(direction="regressed")
    errors = validate_coach_report(coach, _evidence_with_progress("improved"))
    assert any("направлени" in e for e in errors)


def test_progress_confidence_matched_against_drill_progress():
    from coach.validate import validate_coach_report
    # drill_progress.confidence = hypothesis, коуч заявил diagnosis
    coach = _coach_with_progress(confidence="diagnosis")
    errors = validate_coach_report(coach, _evidence_with_progress(confidence="hypothesis"))
    assert any("confidence" in e for e in errors)


def test_progress_metric_absent_from_drill_progress_rejected():
    from coach.validate import validate_coach_report
    ev = _evidence_with_progress()
    ev["drill_progress"] = []                 # движок ничего не репортил
    errors = validate_coach_report(_coach_with_progress(), ev)
    assert any("drill_progress" in e for e in errors)


def test_causal_attribution_rejected_in_progress():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(explanation="точность выросла благодаря дриллу")
    errors = validate_coach_report(coach, _evidence_with_progress())
    assert any("каузальн" in e.lower() or "благодаря" in e for e in errors)


def test_causal_attribution_rejected_in_summary():
    from coach.schema import CoachReport
    from coach.validate import validate_coach_report
    coach = CoachReport(summary="дрилл сработал и всё стало лучше",
                        findings_explained=[], drills=[], caveats=[])
    errors = validate_coach_report(coach, {"episodes": [], "findings": []})
    assert any("каузальн" in e.lower() or "сработал" in e for e in errors)


def test_causal_attribution_rejected_in_caveats():
    from coach.schema import CoachReport
    from coach.validate import validate_coach_report
    coach = CoachReport(summary="ок", findings_explained=[], drills=[],
                        caveats=["прогресс есть благодаря тренировке"])
    errors = validate_coach_report(coach, {"episodes": [], "findings": []})
    assert errors, "каузальность в caveats должна ловиться"


def test_hedged_progress_forbids_assertive_word():
    from coach.validate import validate_coach_report
    coach = _coach_with_progress(confidence="hypothesis",
                                 explanation="точность однозначно движется вниз")
    errors = validate_coach_report(coach, _evidence_with_progress(confidence="hypothesis"))
    assert any("однозначно" in e for e in errors)
```

- [ ] **Step 2: Запустить — падает**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_validate.py -q`
Expected: FAIL (новые проверки ещё не реализованы; напр. каузальность/direction не ловятся).

- [ ] **Step 3: Реализация в `coach/validate.py`**

(1) Добавить каузальный regex рядом с `_ASSERTIVE_STOPWORDS_RE`:
```python
# каузальная атрибуция изменения дриллу — запрещена (адхеренс/конфаундеры
# неизвестны). Предпочитаем over-block: ложный блок ловится ретраем.
_CAUSAL_STOPWORDS_RE = re.compile(
    r"(сработал\w*|благодаря|помог\w*|из-за\s+(?:дрилл|тренировк|упражнени)\w*|"
    r"эффект\s+дрилл\w*|дал\s+результат)",
    re.IGNORECASE,
)


def _check_causal(text: str, where: str) -> List[str]:
    match = _CAUSAL_STOPWORDS_RE.search(text or "")
    if match:
        return [f"каузальная атрибуция '{match.group(0)}' ({where}) — запрещено "
                f"утверждать, что дрилл вызвал изменение (адхеренс/конфаундеры "
                f"неизвестны)"]
    return []
```

(2) В `_known_numbers`, перед `return pool`, добавить пул drill_progress:
```python
    for rec in evidence.get("drill_progress", []):
        pool.extend(float(rec[k]) for k in ("anchor_value", "current_value", "delta")
                    if _is_number(rec.get(k)))
```

(3) В `validate_coach_report`: внутри цикла `findings_explained` добавить каузальный чек (рядом с существующими проверками `fe.explanation`):
```python
        errors.extend(_check_causal(fe.explanation, where))
```
внутри цикла `drills` — рядом с `_check_hu_numbers(drill.rationale, ...)`:
```python
        errors.extend(_check_causal(drill.rationale, where))
```
после `errors.extend(_check_hu_numbers(coach.summary, numbers_known, "summary"))` — каузальность summary + caveats (НОВАЯ поверхность):
```python
    errors.extend(_check_causal(coach.summary, "summary"))
    for caveat in coach.caveats:
        errors.extend(_check_causal(caveat, "caveats"))
```

(4) Там же — блок валидации `progress_explained` (после блока drills, перед `return errors`):
```python
    progress_by_metric = {r["metric"]: r for r in evidence.get("drill_progress", [])}
    for pe in coach.progress_explained:
        where = f"progress '{pe.metric}'"
        rec = progress_by_metric.get(pe.metric)
        if rec is None:
            errors.append(f"{where} отсутствует в drill_progress движка")
            continue
        if pe.direction != rec["direction"]:
            errors.append(f"{where}: коуч заявил направление '{pe.direction}', "
                          f"у движка '{rec['direction']}'")
        if pe.confidence != rec["confidence"]:
            errors.append(f"{where}: коуч заявил confidence '{pe.confidence}', "
                          f"у движка '{rec['confidence']}'")
        errors.extend(_check_hu_numbers(pe.explanation, numbers_known, where))
        errors.extend(_check_causal(pe.explanation, where))
        if pe.confidence in _HEDGED_CONFIDENCES:
            stopword = _ASSERTIVE_STOPWORDS_RE.search(pe.explanation)
            if stopword:
                errors.append(
                    f"утвердительное слово '{stopword.group(1)}' в гипотезе "
                    f"({where}) — гипотеза не должна звучать как диагноз")
    return errors
```

- [ ] **Step 4: Запустить — зелёный (+ регрессия существующих)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_validate.py -q`
Expected: PASS (новые + старые проверки).

- [ ] **Step 5: Commit**

```bash
git add coach/validate.py tests/test_coach_validate.py
git commit -m "feat(coach): guard — заземление дельты/направления + запрет каузальности (summary/caveats/progress)"
```

---

### Task 5: Пайплайн — инжектируемый `history_provider` (тупой добытчик)

**Files:**
- Create: `backend/services/history_provider.py` (чистый `build_clip_snapshots` + `make_history_provider`)
- Modify: `backend/database.py` (`list_sessions_for_player`)
- Modify: `backend/services/analysis_pipeline.py` (`run_pipeline` принимает `history_provider`, зовёт его, передаёт в `build_report`)
- Modify: `backend/main.py` (передать `make_history_provider(db)` в `run_pipeline`)
- Test: `tests/test_history_provider.py` (новый, чистая функция — без БД), `tests/test_analysis_pipeline.py` (дополнить интеграционным тестом с инжектом)

**Interfaces:**
- Produces:
  - `build_clip_snapshots(sessions: Sequence[dict], exclude_clip_id: str) -> List[dict]` — sessions: `{clip_id, created_at, evidence_report(dict|None), coach_report(dict|None)}`. Возвращает `ClipSnapshot`-и (дедуп по clip_id → свежая; исключён текущий; сорт по created_at).
  - `make_history_provider(db) -> Callable[[str, str], List[dict]]`.
  - `run_pipeline(..., history_provider: Optional[Callable] = None)`.
- Consumes: `build_report(drill_history=...)` (Task 2).

- [ ] **Step 1: Написать падающий тест чистой функции**

Создать `tests/test_history_provider.py`:
```python
# -*- coding: utf-8 -*-
"""Тупой добытчик истории (Фаза 2B): снимки из сессий, без БД."""
from backend.services.history_provider import build_clip_snapshots


def _session(clip_id, created_at, findings, drills=None):
    return {
        "clip_id": clip_id, "created_at": created_at,
        "evidence_report": {"findings": findings},
        "coach_report": ({"drills": drills} if drills is not None else None),
    }


def _f(metric, values, conf="diagnosis"):
    return {"metric": metric, "values": values, "confidence": conf}


def test_excludes_current_and_orders_by_time():
    sessions = [
        _session("c2", "2026-07-02T00:00:00", [_f("consistency", {"mae_hu": 4.6})]),
        _session("cur", "2026-07-03T00:00:00", [_f("consistency", {"mae_hu": 4.2})]),
        _session("c1", "2026-07-01T00:00:00", [_f("consistency", {"mae_hu": 5.0})]),
    ]
    snaps = build_clip_snapshots(sessions, exclude_clip_id="cur")
    assert [s["clip_id"] for s in snaps] == ["c1", "c2"]     # текущий исключён, сорт
    assert snaps[0]["findings"]["consistency"]["values"]["mae_hu"] == 5.0


def test_dedup_by_clip_id_keeps_latest():
    sessions = [
        _session("c1", "2026-07-01T00:00:00", [_f("consistency", {"mae_hu": 5.0})]),
        _session("c1", "2026-07-05T00:00:00", [_f("consistency", {"mae_hu": 4.0})]),
    ]
    snaps = build_clip_snapshots(sessions, exclude_clip_id="cur")
    assert len(snaps) == 1
    assert snaps[0]["findings"]["consistency"]["values"]["mae_hu"] == 4.0


def test_assignments_from_coach_drills():
    sessions = [_session(
        "c1", "2026-07-01T00:00:00", [_f("consistency", {"mae_hu": 5.0})],
        drills=[{"target_metric": "consistency",
                 "drill_id": "consistency_t1_vt_ww5t_novice"}])]
    snap = build_clip_snapshots(sessions, "cur")[0]
    assert snap["assignments"] == {"consistency": "consistency_t1_vt_ww5t_novice"}


def test_coach_failed_session_has_empty_assignments():
    sessions = [_session("c1", "2026-07-01T00:00:00",
                         [_f("consistency", {"mae_hu": 5.0})], drills=None)]
    snap = build_clip_snapshots(sessions, "cur")[0]
    assert snap["assignments"] == {} and "consistency" in snap["findings"]


def test_session_without_evidence_report_skipped():
    sessions = [{"clip_id": "c1", "created_at": "2026-07-01T00:00:00",
                 "evidence_report": None, "coach_report": None}]
    assert build_clip_snapshots(sessions, "cur") == []
```

- [ ] **Step 2: Запустить — падает**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_history_provider.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.history_provider'`.

- [ ] **Step 3: Написать `backend/services/history_provider.py`**

```python
# -*- coding: utf-8 -*-
"""Тупой добытчик истории для петли прогресса (Фаза 2B).

Пайплайн — только сбор данных; КАЖДОЕ число считает движок. Читает прошлые
сессии игрока, дедуплицирует по clip_id (свежая побеждает — зеркалит
идемпотентность profile_store), исключает текущий клип, сортирует по времени
и раскладывает в ClipSnapshot-и для engine.compute_drill_progress.
"""
import json
from typing import Callable, List, Optional, Sequence


def build_clip_snapshots(sessions: Sequence[dict],
                         exclude_clip_id: str) -> List[dict]:
    """Сессии (уже распарсенные dict-и) → ClipSnapshot-и. Без БД (тестируемо)."""
    by_clip: dict = {}
    for s in sessions:
        if s["clip_id"] == exclude_clip_id or s.get("evidence_report") is None:
            continue
        prev = by_clip.get(s["clip_id"])
        if prev is None or s["created_at"] > prev["created_at"]:
            by_clip[s["clip_id"]] = s
    snapshots: List[dict] = []
    for s in sorted(by_clip.values(), key=lambda x: x["created_at"]):
        ev = s["evidence_report"]
        findings = {f["metric"]: {"values": f.get("values", {}),
                                  "confidence": f["confidence"]}
                    for f in ev.get("findings", [])}
        coach = s.get("coach_report") or {}
        assignments = {d["target_metric"]: d["drill_id"]
                       for d in coach.get("drills", [])
                       if d.get("target_metric") and d.get("drill_id")}
        snapshots.append({"clip_time": s["created_at"], "clip_id": s["clip_id"],
                          "assignments": assignments, "findings": findings})
    return snapshots


def make_history_provider(db) -> Callable[[str, str], List[dict]]:
    """Дефолтный провайдер: читает AnalysisSession через DatabaseManager."""
    def provider(player_id: str, exclude_clip_id: str) -> List[dict]:
        rows = db.list_sessions_for_player(player_id)
        sessions = [{
            "clip_id": r.clip_id, "created_at": r.created_at.isoformat(),
            "evidence_report": (json.loads(r.evidence_report)
                                if r.evidence_report else None),
            "coach_report": (json.loads(r.coach_report)
                             if r.coach_report else None),
        } for r in rows]
        return build_clip_snapshots(sessions, exclude_clip_id)
    return provider
```

- [ ] **Step 4: Запустить чистый тест — зелёный**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_history_provider.py -q`
Expected: PASS.

- [ ] **Step 5: DB-метод + проводка пайплайна**

В `backend/database.py`: расширить импорт `from sqlmodel import Field, Session, SQLModel, create_engine, select` (добавить `select`) и добавить метод в `DatabaseManager`:
```python
    def list_sessions_for_player(self, player_id: str):
        with Session(self.engine) as session:
            return list(session.exec(
                select(AnalysisSession).where(
                    AnalysisSession.player_id == player_id)).all())
```

В `backend/services/analysis_pipeline.py`: (1) сигнатура `run_pipeline` получает `history_provider: Optional[Callable] = None`; (2) перед вызовом `build_report` собрать историю и передать:
```python
    provider = history_provider or (lambda pid, cid: [])
    drill_history = provider(player_id, ctx.clip_id)

    report = build_report(ctx, samples, episodes, duel_hu=cfg.duel_hu,
                          profile=profile, drill_history=drill_history)
```

В `backend/main.py`: импорт `from backend.services.history_provider import make_history_provider` и в вызове `run_pipeline` (строки ~70-73) добавить аргумент:
```python
        result = await loop.run_in_executor(None, lambda: run_pipeline(
            video_path, player_id, clip_id=clip_id, sens=sens, edpi=edpi,
            agent=agent, map_name=map_name,
            evidence_dir=session_evidence_dir, on_status=on_status,
            history_provider=make_history_provider(db)))
```

- [ ] **Step 6: Интеграционный тест пайплайна (инжект провайдера)**

Дописать в `tests/test_analysis_pipeline.py` (использует существующие `video`, `FakeDetector`, `FakeCoach`, `synthetic_heads`, `_DRILL_ID_BY_METRIC`):
```python
def test_pipeline_emits_drill_progress_from_injected_history(video, tmp_path):
    """history_provider инжектится; drill_progress появляется в отчёте."""
    metric = "consistency"

    def provider(player_id, exclude_clip_id):
        return [{
            "clip_time": "2026-07-01T00:00:00", "clip_id": "prev",
            "assignments": {metric: _DRILL_ID_BY_METRIC[metric]},
            "findings": {metric: {"values": {"mae_hu": 99.0},
                                  "confidence": "diagnosis"}},
        }]

    config = PipelineConfig(profile_dir=str(tmp_path / "profiles"))
    result = run_pipeline(
        str(video), "p1", clip_id="cur", config=config,
        evidence_dir=str(tmp_path / "evidence"),
        detector=FakeDetector(synthetic_heads()), coach_client=FakeCoach(),
        history_provider=provider)

    progress = result.evidence_report["drill_progress"]
    rec = next(r for r in progress if r["metric"] == metric)
    assert rec["anchor_clip_id"] == "prev" and rec["anchor_value"] == 99.0
    assert rec["direction"] == "improved"        # текущий mae << 99 → улучшение


def test_pipeline_no_history_empty_drill_progress(video, tmp_path):
    result = _run(video, tmp_path)               # дефолтный провайдер отсутствует → []
    assert result.evidence_report["drill_progress"] == []
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_analysis_pipeline.py tests/test_history_provider.py -q`
Expected: PASS (пайплайн-тесты гоняются в .venv — синтетическое cv2-видео, без torch/API/БД).

- [ ] **Step 7: Commit**

```bash
git add backend/services/history_provider.py backend/database.py backend/services/analysis_pipeline.py backend/main.py tests/test_history_provider.py tests/test_analysis_pipeline.py
git commit -m "feat(backend): инжектируемый history_provider — снимки истории в drill_progress"
```

---

### Task 6: Зелёный прогон, verify-пункт фронта, отсутствие регрессий

- [ ] **Step 1: Полный прогон затронутых наборов**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_criterion_helper.py tests/test_drill_catalog.py tests/test_drill_progress.py tests/test_coach_schema.py tests/test_coach_prompt.py tests/test_coach_validate.py tests/test_history_provider.py tests/test_analysis_pipeline.py -q`
Expected: PASS (все наборы 2B + регрессия каталога/пайплайна зелёные).

- [ ] **Step 2: Отсутствие НОВЫХ падений по всему движку/коучу**

Run: `.\.venv\Scripts\python.exe -m pytest -q --continue-on-collection-errors --ignore=tests/test_backend_api.py`
Expected: те же pre-existing `dataset1/*`-падения (`FileNotFoundError` real-clip тесты), НО ноль НОВЫХ падений из-за 2B. Наборы 2B зелёные.

> Заметка: `.venv` не содержит `dataset1/` и части backend-зависимостей — pre-existing окружение, НЕ регрессия. Ориентир — отсутствие НОВЫХ падений относительно baseline после 2A.

- [ ] **Step 3: Verify-пункт фронта (граница «не трогаем, но не ломаем»)**

`drill_progress` (в evidence_report) и `progress_explained` (в CoachReport) — новые ключи; фронт их НЕ рендерит в 2B. Убедиться, что React (CRA) игнорит неизвестные ключи и сборка не падает:
```powershell
cd frontend ; npm run build
```
Expected: сборка успешна (новые ключи не роняют `ReportView`; фронт-код не менялся). Если нет node_modules — `npm install` сперва. Это verify-проверка границы, не код-таск.

- [ ] **Step 4: Финальный коммит (если остались правки)**

```bash
git add -A
git commit -m "test: зелёный прогон Фазы 2B — петля прогресса на engine-сигнале"
```

---

## Self-Review

**Spec coverage (2026-07-07-phase2b-progress-loop-design.md):**
- Компонент 1 (общий хелпер, нейтральный dict, анти-цикл) → Task 1 (`compute_metric_criterion`/`normalize` + рефактор `build_criterion` + греп-гард тест). ✅
- Компонент 2 (`drill_progress`: кумулятивный anchor, разрыв по резолюции ≥hypothesis, correction единый anchor, min-confidence, вырожденец skip, null-current, `_r`-точность, детерминированный порядок, ретро-пустота, запись) → Task 2 (полная edge-матрица + граничный тест округления). ✅
- Компонент 3 (guard: пул += drill_progress; структурное `progress_explained` enum-direction; каузальный бан явно на summary/caveats/progress/rationale/findings; confidence против drill_progress; metric вне drill_progress → reject; hedged→no-assertive) → Task 3 (схема+промпт) + Task 4 (валидатор, тест каузального бана на summary/caveats/progress). ✅
- Компонент 4 (инжектируемый `history_provider`, дедуп по clip_id, исключение текущего, coach_failed→assignments={}, CLI→[]) → Task 5 (чистый `build_clip_snapshots` + `make_history_provider` + проводка). ✅
- Границы (фронт не трогаем + verify-пункт; UI/API/Steam/jitter/tier → 2C; аддитивный `drill_history=()`) → Task 6 (verify фронта) + отражено в Global Constraints. ✅
- Единая нормировка + точность (`normalize` = трансформ baseline вкл. округление; `delta=_r`, не integer) → Task 1 (`normalize`) + Task 2 (граничный тест). ✅

**Placeholder scan:** полный код в каждом шаге (импл + тесты); команды с ожидаемым выводом; никаких «TBD»/«аналогично Task N»/«добавить обработку». Единственные ссылки на «сверься с файлом» — на СУЩЕСТВУЮЩИЕ тест-хелперы (`test_coach_validate.py`, `test_analysis_pipeline.py`), чьи фикстуры в плане приведены самодостаточно.

**Type consistency:** `compute_metric_criterion` возвращает dict с ключами `{value_key, comparator, target, baseline, directional_meaningful}` — одинаково в Task 1 (определение), Task 2 (потребление). `normalize(value_key, raw)` — Task 1 определяет, Task 2 зовёт. `ClipSnapshot`/запись `drill_progress` — поля согласованы между Task 2 (эмиссия), Task 4 (чтение `direction`/`confidence`/`anchor_value`/`current_value`/`delta`), Task 5 (сборка снимка `{clip_time, clip_id, assignments, findings}`). `ProgressExplained{metric, direction, confidence, explanation}` — Task 3 определяет, Task 4 читает. `build_report(..., drill_history=())` — Task 2 сигнатура, Task 5 передаёт. `list_sessions_for_player` — Task 5 определяет и зовёт.
