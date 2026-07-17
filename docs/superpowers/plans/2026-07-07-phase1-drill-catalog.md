# Фаза 1: детерминированный каталог дриллов Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Развернуть поток дриллов так, чтобы движок владел каталогом и числовыми критериями, а VLM только выбирал `drill_id` и объяснял выбор — закрыв нарушение принципа «числа считает ТОЛЬКО движок».

**Architecture:** VLM возвращает `DrillSelection {priority, drill_id, rationale}`. После groundedness-валидации пайплайн (и офлайн-CLI) детерминированно собирает финальный `Drill` из `coach/drill_catalog.py` (`name/platform/dose/tier` из каталога, `SuccessCriterion` из `values` соответствующего finding). Валидатор проверяет `drill_id ∈ каталог` **и** его метрика есть среди findings; чисел от VLM в дриллах больше нет. Если среди findings нет ни одного диагноза — план урезается до топ-1–2 + CTA-caveat.

**Tech Stack:** Python 3, Pydantic v2, pytest; React 18 (CRA) на фронте.

## Global Constraints

- Python только через `.\.venv\Scripts\python.exe` (каталог `venv\` сломан).
- Тесты: `.\.venv\Scripts\python.exe -m pytest -q`.
- Управляющий принцип: любые числа в отчёте происходят из движка; VLM их не производит.
- Per-player: людей не сливаем; `--player-id`/`player_id` обязателен (эту фазу не трогает, но не нарушать).
- `conf=0.4` YOLO зафиксирован — не касаться.
- Неймспейс `drill_id` фиксируется в этой фазе и НЕ переименовывается позже (Фаза 2 ключуется на него).
- `DrillSelection` НЕ несёт поле `tier` (первый клип всегда tier 1) и НЕ несёт `dose_override`.
- **Каталог — Voltaic S5** (evxl.app, скриншоты пользователя): core-семейства `ww5t` (consistency), `1wNts` (bias), `Pasu` (correction); `placement` — in-game (у Voltaic нет пре-айма). Пороги рангов S5 (Iron…Celestial) записываются в каталог.
- Язык кода/комментариев — как в окружающих файлах (русскоязычные докстроки, английские идентификаторы).

---

### Task 1: Схема — DrillSelection, SuccessCriterion, финальный Drill

**Files:**
- Modify: `coach/schema.py`
- Test: `tests/test_coach_schema.py`

**Interfaces:**
- Produces:
  - `class DrillSelection(BaseModel)`: `priority: int`, `drill_id: str`, `rationale: str`.
  - `class SuccessCriterion(BaseModel)`: `metric: str`, `value_key: str`, `comparator: str`, `target: Optional[float]`, `baseline: Optional[float]`, `text: str`.
  - `class Drill(BaseModel)` (финальный, собирает движок): `priority: int`, `drill_id: str`, `name: str`, `platform: Platform`, `tier: int`, `dose: str`, `target_metric: str`, `rationale: str`, `success_criterion: str`, `criterion: SuccessCriterion`.
  - `CoachReport.drills: List[DrillSelection]` (VLM-выход; финальные `Drill` подставляются после сборки, вне контракта structured output).

- [ ] **Step 1: Write the failing test**

Заменить блок дриллов в `tests/test_coach_schema.py`. В `_valid_report_dict()` заменить `"drills"` на список `DrillSelection`:

```python
        "drills": [
            {
                "priority": 1,
                "drill_id": "consistency_t1_vt_ww5t_novice",
                "rationale": "Разброс низкий, ошибка высокая — нужна повторяемость.",
            }
        ],
```

и обновить `test_valid_report_parses`:

```python
def test_valid_report_parses():
    report = CoachReport.model_validate(_valid_report_dict())
    assert report.findings_explained[0].metric == "consistency"
    assert report.drills[0].drill_id == "consistency_t1_vt_ww5t_novice"
    assert report.drills[0].priority == 1
```

Убрать `test_invalid_platform_rejected` (в `DrillSelection` платформы нет) и заменить импорт/добавить тесты финальных типов:

```python
from coach.schema import (CoachReport, Drill, DrillSelection,
                          FindingExplained, SuccessCriterion)


def test_drill_selection_requires_drill_id():
    with pytest.raises(ValidationError):
        DrillSelection.model_validate({"priority": 1, "rationale": "x"})


def test_final_drill_carries_structured_criterion():
    drill = Drill(
        priority=1,
        drill_id="consistency_t1_vt_ww5t_novice",
        name="VT ww5t Novice S5",
        platform="kovaaks",
        tier=1,
        dose="3 подхода по 5 минут",
        target_metric="consistency",
        rationale="повторяемость",
        success_criterion="Средняя ошибка в дуэли < 1.147 HU на следующем клипе.",
        criterion=SuccessCriterion(
            metric="consistency", value_key="mae_hu", comparator="<",
            target=1.147, baseline=1.349,
            text="Средняя ошибка в дуэли < 1.147 HU на следующем клипе.",
        ),
    )
    assert drill.criterion.baseline == 1.349
    assert drill.tier == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_schema.py -q`
Expected: FAIL с `ImportError: cannot import name 'DrillSelection'` / `SuccessCriterion`.

- [ ] **Step 3: Write minimal implementation**

Заменить блоки `Drill`/`CoachReport` в `coach/schema.py` (оставить `FindingExplained`, `Confidence`, `Platform` без изменений):

```python
from typing import List, Literal, Optional

from pydantic import BaseModel

Confidence = Literal["diagnosis", "hypothesis", "insufficient"]

Platform = Literal["kovaaks", "range", "ingame"]


class FindingExplained(BaseModel):
    """Объяснение одного finding движка со ссылками на кадры-улики."""

    metric: str
    explanation: str
    evidence_frames: List[int]
    confidence: Confidence


class DrillSelection(BaseModel):
    """Выбор VLM: id упражнения из каталога движка + приоритет + обоснование.

    VLM НЕ производит ни названий, ни чисел — их детерминированно
    подставляет движок (coach/drill_catalog.py) после валидации."""

    priority: int
    drill_id: str
    rationale: str


class SuccessCriterion(BaseModel):
    """Числовой критерий успеха, посчитанный движком из values finding-а.

    Строка `text` — для UI; остальные поля структурны для машинной сверки
    на следующем клипе (Фаза 2)."""

    metric: str
    value_key: str
    comparator: str            # "<" | "count_le" | "direction"
    target: Optional[float]
    baseline: Optional[float]
    text: str


class Drill(BaseModel):
    """Финальный дрилл, собранный движком из DrillSelection + каталога."""

    priority: int
    drill_id: str
    name: str
    platform: Platform
    tier: int
    dose: str
    target_metric: str
    rationale: str
    success_criterion: str
    criterion: SuccessCriterion


class CoachReport(BaseModel):
    """Коучинг-отчёт: портрет, объяснения, ВЫБОР дриллов, ограничения.

    drills — сырой выбор VLM (DrillSelection); финальные Drill подставляет
    движок после сборки и не участвуют в structured output контракте."""

    summary: str
    findings_explained: List[FindingExplained]
    drills: List[DrillSelection]
    caveats: List[str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/schema.py tests/test_coach_schema.py
git commit -m "feat(coach): DrillSelection + SuccessCriterion, финальный Drill собирает движок"
```

---

### Task 2: Каталог дриллов S5 + детерминированные критерии

**Files:**
- Create: `coach/drill_catalog.py`
- Test: `tests/test_drill_catalog.py`

**Interfaces:**
- Consumes: `coach.schema.DrillSelection`, `coach.schema.Drill`, `coach.schema.SuccessCriterion`.
- Produces:
  - `@dataclass(frozen=True) class CatalogDrill`: `drill_id, name, platform, tier, metric, dose, instruction, rank_thresholds`.
  - `CATALOG: Dict[str, List[CatalogDrill]]` (ключ — метрика).
  - `get_catalog_drill(drill_id: str) -> Optional[CatalogDrill]`.
  - `build_criterion(metric: str, values: dict) -> SuccessCriterion`.
  - `assemble_drill(selection: DrillSelection, finding: dict) -> Drill`.
  - `menu_for_prompt() -> str` (только tier-1 core-дриллы).
  - `@dataclass class FinalizedPlan`: `drills: List[Drill]`, `extra_caveats: List[str]`.
  - `finalize_plan(selections: Sequence[DrillSelection], findings: Sequence[dict]) -> FinalizedPlan`.

**drill_id (зафиксированы, S5):**
- placement: `placement_t1_range_preaim_walk`, `placement_t2_valorant_clear_angles`, `placement_t3_valorant_deathmatch`
- consistency: `consistency_t1_vt_ww5t_novice`, `consistency_t2_vt_ww5t_intermediate`, `consistency_t3_vt_ww5t_advanced`
- bias: `bias_t1_vt_1w4ts_novice`, `bias_t2_vt_1w3ts_intermediate`, `bias_t3_vt_1w2ts_advanced`
- correction: `correction_t1_vt_pasu_novice`, `correction_t2_vt_pasu_intermediate`, `correction_t3_vt_pasu_advanced`

- [ ] **Step 1: Write the failing test**

Создать `tests/test_drill_catalog.py`:

```python
# -*- coding: utf-8 -*-
"""Тесты детерминированного каталога дриллов Voltaic S5 (Фаза 1)."""
from coach.drill_catalog import (CATALOG, FinalizedPlan, assemble_drill,
                                 build_criterion, finalize_plan,
                                 get_catalog_drill, menu_for_prompt)
from coach.schema import DrillSelection

CORE_METRICS = {"placement", "consistency", "bias", "correction"}


def _finding(metric, values, confidence="diagnosis"):
    return {"metric": metric, "values": values, "confidence": confidence}


# ---- целостность каталога -------------------------------------------------

def test_every_core_metric_has_three_tiers():
    for metric in CORE_METRICS:
        tiers = sorted(d.tier for d in CATALOG[metric])
        assert tiers == [1, 2, 3], metric


def test_drill_ids_unique_across_catalog():
    ids = [d.drill_id for drills in CATALOG.values() for d in drills]
    assert len(ids) == len(set(ids))


def test_get_catalog_drill_roundtrip():
    cd = get_catalog_drill("consistency_t1_vt_ww5t_novice")
    assert cd is not None and cd.metric == "consistency" and cd.tier == 1


def test_get_catalog_drill_unknown_is_none():
    assert get_catalog_drill("does_not_exist") is None


def test_menu_lists_only_tier1_core_drills():
    menu = menu_for_prompt()
    assert "consistency_t1_vt_ww5t_novice" in menu
    assert "consistency_t2_vt_ww5t_intermediate" not in menu
    for metric in CORE_METRICS:
        t1 = next(d for d in CATALOG[metric] if d.tier == 1)
        assert t1.drill_id in menu


# ---- пороги рангов S5 -----------------------------------------------------

def test_voltaic_tier_close_thresholds():
    # верхний ранг тира = «закрыть тир»: Novice→Gold, Adv→Celestial
    assert get_catalog_drill(
        "consistency_t1_vt_ww5t_novice").rank_thresholds["gold"] == 1290
    assert get_catalog_drill(
        "bias_t2_vt_1w3ts_intermediate").rank_thresholds["master"] == 1380
    assert get_catalog_drill(
        "correction_t3_vt_pasu_advanced").rank_thresholds["celestial"] == 1240


def test_placement_has_no_voltaic_thresholds():
    for cd in CATALOG["placement"]:
        assert cd.rank_thresholds is None


# ---- критерии на реальной форме values ------------------------------------

def test_consistency_criterion_is_15pct_relative():
    c = build_criterion("consistency", {"mae_hu": 1.349, "std_hu": 0.7})
    assert c.value_key == "mae_hu" and c.comparator == "<"
    assert c.baseline == 1.349 and c.target == 1.147   # round(1.349*0.85, 3)


def test_placement_criterion_is_count_reduction():
    c = build_criterion("placement", {"total": 10, "below": 7, "mean_dy_hu": -1.4})
    assert c.value_key == "below" and c.comparator == "count_le"
    assert c.baseline == 7 and c.target == 2           # round(0.2*10)


def test_bias_criterion_halves_absolute_y():
    c = build_criterion("bias", {"y_bias_hu": -1.2, "x_bias_hu": 0.1})
    assert c.comparator == "<" and c.baseline == 1.2 and c.target == 0.6


def test_correction_criterion_is_directional_not_threshold():
    c = build_criterion("correction", {"flicks_analysed": 8, "x_overshoots": 5,
                                       "x_undershoots": 1, "y_overshoots": 0,
                                       "y_undershoots": 1})
    assert c.comparator == "direction" and c.target is None
    assert "перел" in c.text.lower()


def test_criterion_handles_missing_value():
    c = build_criterion("consistency", {"mae_hu": None})
    assert c.target is None and "клип" in c.text.lower()


# ---- сборка ---------------------------------------------------------------

def test_assemble_drill_pulls_name_from_catalog():
    sel = DrillSelection(priority=1,
                         drill_id="consistency_t1_vt_ww5t_novice",
                         rationale="повторяемость")
    drill = assemble_drill(sel, _finding("consistency", {"mae_hu": 1.349}))
    assert drill.name == get_catalog_drill(sel.drill_id).name
    assert drill.tier == 1 and drill.target_metric == "consistency"
    assert drill.criterion.baseline == 1.349
    assert drill.rationale == "повторяемость"


# ---- честность плана ------------------------------------------------------

def test_finalize_trims_to_two_when_no_diagnosis():
    findings = [_finding("placement", {"total": 5, "below": 4, "mean_dy_hu": -1},
                         confidence="hypothesis"),
                _finding("consistency", {"mae_hu": 1.3}, confidence="hypothesis"),
                _finding("bias", {"y_bias_hu": -0.9}, confidence="hypothesis"),
                _finding("correction", {"flicks_analysed": 2, "x_overshoots": 1,
                                        "x_undershoots": 0, "y_overshoots": 0,
                                        "y_undershoots": 0}, confidence="hypothesis")]
    sels = [
        DrillSelection(priority=1, drill_id="placement_t1_range_preaim_walk", rationale="a"),
        DrillSelection(priority=2, drill_id="consistency_t1_vt_ww5t_novice", rationale="b"),
        DrillSelection(priority=3, drill_id="bias_t1_vt_1w4ts_novice", rationale="c"),
        DrillSelection(priority=4, drill_id="correction_t1_vt_pasu_novice", rationale="d"),
    ]
    plan = finalize_plan(sels, findings)
    assert len(plan.drills) == 2
    assert [d.priority for d in plan.drills] == [1, 2]
    assert plan.extra_caveats and "клип" in plan.extra_caveats[0].lower()


def test_finalize_keeps_all_when_diagnosis_present():
    findings = [_finding("consistency", {"mae_hu": 1.3}, confidence="diagnosis"),
                _finding("bias", {"y_bias_hu": -0.9}, confidence="hypothesis")]
    sels = [
        DrillSelection(priority=2, drill_id="bias_t1_vt_1w4ts_novice", rationale="b"),
        DrillSelection(priority=1, drill_id="consistency_t1_vt_ww5t_novice", rationale="a"),
    ]
    plan = finalize_plan(sels, findings)
    assert [d.priority for d in plan.drills] == [1, 2]   # отсортировано
    assert plan.extra_caveats == []


def test_finalize_skips_selection_without_finding():
    findings = [_finding("consistency", {"mae_hu": 1.3}, confidence="diagnosis")]
    sels = [DrillSelection(priority=1, drill_id="bias_t1_vt_1w4ts_novice", rationale="b")]
    plan = finalize_plan(sels, findings)
    assert plan.drills == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_drill_catalog.py -q`
Expected: FAIL с `ModuleNotFoundError: No module named 'coach.drill_catalog'`.

- [ ] **Step 3: Write minimal implementation**

Создать `coach/drill_catalog.py`:

```python
# -*- coding: utf-8 -*-
"""Детерминированный каталог дриллов + числовые критерии успеха (Фаза 1).

Движок владеет каталогом и числами; VLM выбирает drill_id и объясняет.
Имена/пороги сценариев — Voltaic S5 (evxl.app, 2026-07): consistency→ww5t
(сустейн-повторяемость), bias→1wNts (точная одиночная постановка, целей
меньше с тиром), correction→Pasu (реактивный флик). placement — in-game
(у Voltaic нет пре-айм-сценария). drill_id стабильны — Фаза 2 ключуется на
них, переименование рвёт историю. Пороги = верхние ранги тиров S5.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from coach.schema import Drill, DrillSelection, SuccessCriterion

CORE_METRICS = ("placement", "consistency", "bias", "correction")

# Ручки критериев в одном месте (доменная правка не трогает логику).
PLACEMENT_TARGET_FRACTION = 0.2
CONSISTENCY_IMPROVEMENT = 0.15     # MAE < base * 0.85
BIAS_HALVE_FACTOR = 0.5


@dataclass(frozen=True)
class CatalogDrill:
    """Одно упражнение каталога: id, название, платформа, тир, метрика, доза.

    rank_thresholds — пороги рангов Voltaic S5 для сценария этого тира
    (ранг→score); None для in-game placement (у Voltaic нет пре-айма).
    Читается Фазой 2C (двухсигнальная прогрессия), в Фазе 1 не потребляется."""
    drill_id: str
    name: str
    platform: str          # "kovaaks" | "range" | "ingame"
    tier: int              # 1 Novice | 2 Intermediate | 3 Advanced
    metric: str
    dose: str              # доза-плейсхолдер; пользователь тюнит доменно
    instruction: str       # фокус инструкции (разводит bias/consistency)
    rank_thresholds: Optional[Dict[str, int]] = None


# Семантика тиров = сложность механики в тренажёре (перенос в игру меряет
# движок на клипах отдельно). placement — исключение: все тиры in-game.
CATALOG: Dict[str, List[CatalogDrill]] = {
    "placement": [
        CatalogDrill("placement_t1_range_preaim_walk",
                     "Range: pre-aim walk на уровне головы", "range", 1,
                     "placement", "5 минут разминкой",
                     "Иди по полигону, держа прицел строго на линии головы, без стрельбы."),
        CatalogDrill("placement_t2_valorant_clear_angles",
                     "Valorant: clear angles (пре-айм типовых углов)", "ingame", 2,
                     "placement", "10 минут перед сессией",
                     "Пре-айм типовых углов сайта на уровне головы до входа."),
        CatalogDrill("placement_t3_valorant_deathmatch",
                     "Valorant Deathmatch: пре-айм под давлением", "ingame", 3,
                     "placement", "1 матч DM в день",
                     "Держи прицел на линии головы в движении и под давлением."),
    ],
    "consistency": [
        CatalogDrill("consistency_t1_vt_ww5t_novice",
                     "VT ww5t Novice S5", "kovaaks", 1,
                     "consistency", "3 подхода по 5 минут",
                     "Сустейн-повторяемость: держи темп, минимизируй разброс попаданий.",
                     {"iron": 990, "bronze": 1090, "silver": 1190, "gold": 1290}),
        CatalogDrill("consistency_t2_vt_ww5t_intermediate",
                     "VT ww5t Intermediate S5", "kovaaks", 2,
                     "consistency", "3 подхода по 5 минут",
                     "Та же повторяемость под возросшим темпом/точностью.",
                     {"platinum": 1310, "diamond": 1400, "jade": 1490, "master": 1560}),
        CatalogDrill("consistency_t3_vt_ww5t_advanced",
                     "VT ww5t Advanced S5", "kovaaks", 3,
                     "consistency", "3 подхода по 5 минут",
                     "Повторяемость на соревновательном темпе.",
                     {"grandmaster": 1510, "nova": 1610, "astra": 1720, "celestial": 1860}),
    ],
    "bias": [
        CatalogDrill("bias_t1_vt_1w4ts_novice",
                     "VT 1w4ts Novice S5", "kovaaks", 1,
                     "bias", "3 подхода по 5 минут",
                     "Точная одиночная постановка — здесь видно систематическое смещение прицела.",
                     {"iron": 820, "bronze": 915, "silver": 1010, "gold": 1110}),
        CatalogDrill("bias_t2_vt_1w3ts_intermediate",
                     "VT 1w3ts Intermediate S5", "kovaaks", 2,
                     "bias", "3 подхода по 5 минут",
                     "Меньше целей, выше требования к точной постановке.",
                     {"platinum": 1120, "diamond": 1220, "jade": 1300, "master": 1380}),
        CatalogDrill("bias_t3_vt_1w2ts_advanced",
                     "VT 1w2ts Advanced S5", "kovaaks", 3,
                     "bias", "3 подхода по 5 минут",
                     "Одиночная постановка на соревновательной точности.",
                     {"grandmaster": 1320, "nova": 1420, "astra": 1520, "celestial": 1620}),
    ],
    "correction": [
        CatalogDrill("correction_t1_vt_pasu_novice",
                     "VT Pasu Novice S5", "kovaaks", 1,
                     "correction", "3 подхода по 5 минут",
                     "Реактивный флик к цели: гаси перелёт доводкой, не проскакивай.",
                     {"iron": 555, "bronze": 660, "silver": 745, "gold": 800}),
        CatalogDrill("correction_t2_vt_pasu_intermediate",
                     "VT Pasu Intermediate S5", "kovaaks", 2,
                     "correction", "3 подхода по 5 минут",
                     "Тот же флик под возросшей амплитудой/темпом.",
                     {"platinum": 770, "diamond": 850, "jade": 930, "master": 980}),
        CatalogDrill("correction_t3_vt_pasu_advanced",
                     "VT Pasu Advanced S5", "kovaaks", 3,
                     "correction", "3 подхода по 5 минут",
                     "Флик близко к соревновательной механике.",
                     {"grandmaster": 910, "nova": 1020, "astra": 1110, "celestial": 1240}),
    ],
}

_CATALOG_BY_ID: Dict[str, CatalogDrill] = {
    d.drill_id: d for drills in CATALOG.values() for d in drills
}


def get_catalog_drill(drill_id: str) -> Optional[CatalogDrill]:
    return _CATALOG_BY_ID.get(drill_id)


def menu_for_prompt() -> str:
    """Меню tier-1 core-дриллов для промпта (первый клип всегда tier 1)."""
    lines = ["Меню дриллов (выбирай drill_id ТОЛЬКО отсюда):"]
    for metric in CORE_METRICS:
        cd = next(d for d in CATALOG[metric] if d.tier == 1)
        lines.append(f"- {cd.drill_id} (метрика {metric}): {cd.name}")
    return "\n".join(lines)


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    return None if x is None else round(x, digits)


def build_criterion(metric: str, values: dict) -> SuccessCriterion:
    """Детерминированный критерий из values finding-а (число считает движок)."""
    if metric == "placement":
        total = values.get("total")
        below = values.get("below")
        if total is None or below is None:
            return SuccessCriterion(metric=metric, value_key="below",
                                    comparator="count_le", target=None, baseline=None,
                                    text="Нужен ещё клип для числового критерия пре-айма.")
        target = round(PLACEMENT_TARGET_FRACTION * total)
        return SuccessCriterion(
            metric=metric, value_key="below", comparator="count_le",
            target=float(target), baseline=float(below),
            text=(f"Довести число появлений с прицелом ниже линии головы до "
                  f"≤ {target} из {total} (сейчас {below}); средний "
                  f"вертикальный промах — к нулю."))
    if metric == "consistency":
        base = values.get("mae_hu")
        if base is None:
            return SuccessCriterion(metric=metric, value_key="mae_hu",
                                    comparator="<", target=None, baseline=None,
                                    text="Нужен ещё клип для числового критерия точности.")
        target = _r(base * (1 - CONSISTENCY_IMPROVEMENT))
        return SuccessCriterion(
            metric=metric, value_key="mae_hu", comparator="<",
            target=target, baseline=_r(base),
            text=(f"Средняя ошибка в дуэли < {target} HU "
                  f"(−{int(CONSISTENCY_IMPROVEMENT * 100)}% к текущим "
                  f"{_r(base)} HU) на следующем клипе."))
    if metric == "bias":
        raw = values.get("y_bias_hu")
        if raw is None:
            return SuccessCriterion(metric=metric, value_key="y_bias_hu",
                                    comparator="<", target=None, baseline=None,
                                    text="Нужен ещё клип для числового критерия смещения.")
        base = abs(raw)
        target = _r(base * BIAS_HALVE_FACTOR)
        return SuccessCriterion(
            metric=metric, value_key="y_bias_hu", comparator="<",
            target=target, baseline=_r(base),
            text=(f"Систематическое вертикальное смещение |Y| < {target} HU "
                  f"(вдвое меньше текущих {_r(base)} HU)."))
    if metric == "correction":
        pairs = [("X", "перелёт", values.get("x_overshoots", 0)),
                 ("X", "недолёт", values.get("x_undershoots", 0)),
                 ("Y", "перелёт", values.get("y_overshoots", 0)),
                 ("Y", "недолёт", values.get("y_undershoots", 0))]
        axis, kind, count = max(pairs, key=lambda p: p[2])
        analysed = values.get("flicks_analysed", 0)
        if count == 0:
            text = "Держать чистые флики без перелёта и недолёта на следующем клипе."
            value_key = "flicks_analysed"
        else:
            text = (f"Снизить долю {kind}ов по оси {axis}: сейчас {count} из "
                    f"{analysed} фликов — двигать в сторону чистых фликов "
                    f"(прокси-метрика, без жёсткого порога).")
            value_key = f"{axis.lower()}_{'overshoots' if kind == 'перелёт' else 'undershoots'}"
        return SuccessCriterion(metric=metric, value_key=value_key,
                                comparator="direction", target=None,
                                baseline=float(count), text=text)
    raise ValueError(f"неизвестная метрика критерия: {metric}")


def assemble_drill(selection: DrillSelection, finding: dict) -> Drill:
    """Финальный Drill: имя/платформа/доза/тир из каталога, критерий из values."""
    cd = _CATALOG_BY_ID[selection.drill_id]
    criterion = build_criterion(cd.metric, finding.get("values", {}))
    return Drill(
        priority=selection.priority,
        drill_id=cd.drill_id,
        name=cd.name,
        platform=cd.platform,
        tier=cd.tier,
        dose=cd.dose,
        target_metric=cd.metric,
        rationale=selection.rationale,
        success_criterion=criterion.text,
        criterion=criterion,
    )


@dataclass
class FinalizedPlan:
    """Собранный план: финальные дриллы + добавочные оговорки (честность)."""
    drills: List[Drill] = field(default_factory=list)
    extra_caveats: List[str] = field(default_factory=list)


def finalize_plan(selections: Sequence[DrillSelection],
                  findings: Sequence[dict]) -> FinalizedPlan:
    """Сборка + правило честности: без единого диагноза план урезается до топ-2."""
    by_metric = {f["metric"]: f for f in findings}
    drills: List[Drill] = []
    for sel in selections:
        cd = _CATALOG_BY_ID.get(sel.drill_id)
        if cd is None or cd.metric not in by_metric:
            continue                       # валидатор уже страхует; защитно
        drills.append(assemble_drill(sel, by_metric[cd.metric]))
    drills.sort(key=lambda d: d.priority)
    extra: List[str] = []
    has_diagnosis = any(f.get("confidence") == "diagnosis" for f in findings)
    if not has_diagnosis and len(drills) > 2:
        drills = drills[:2]
        extra.append(
            "Пока ни один вывод не дотянул до уверенного диагноза — план "
            "сокращён до 1–2 главных гипотез. Запиши ещё 1–2 клипа, чтобы "
            "движок подтвердил закономерности.")
    return FinalizedPlan(drills=drills, extra_caveats=extra)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_drill_catalog.py -q`
Expected: PASS (все ~16 тестов).

- [ ] **Step 5: Commit**

```bash
git add coach/drill_catalog.py tests/test_drill_catalog.py
git commit -m "feat(coach): каталог дриллов Voltaic S5 + критерии + пороги рангов + честность плана"
```

---

### Task 3: Валидатор — проверка drill_id ↔ каталог ↔ finding

**Files:**
- Modify: `coach/validate.py:117-158` (тело `validate_coach_report`, блок дриллов)
- Modify: `tests/test_coach_validate.py` (фикстура `_coach` + drill-тесты)
- Modify (fixtures): `reports/coach_friend_clip3.json`, `reports/coach_author_output_clip.json` (миграция `drills` на DrillSelection)

**Interfaces:**
- Consumes: `coach.drill_catalog.get_catalog_drill`.
- Produces: `validate_coach_report(coach, evidence)` — для каждого `DrillSelection`: ошибка если `drill_id ∉ каталог` или его метрика ∉ findings; `rationale` проверяется на HU-groundedness тем же `_check_hu_numbers`.

- [ ] **Step 1: Write the failing test**

В `tests/test_coach_validate.py` заменить импорт и фикстуру `_coach`:

```python
from coach.schema import CoachReport, DrillSelection, FindingExplained
```

```python
def _coach(
    metric: str = "consistency",
    explanation: str = "Ошибка MAE 1.349 HU при разбросе std 0.764 HU.",
    frames: Optional[List[int]] = None,
    confidence: str = "diagnosis",
    drill_id: str = "consistency_t1_vt_ww5t_novice",
    rationale: str = "Разброс низкий, ошибка высокая — нужна повторяемость.",
) -> CoachReport:
    return CoachReport(
        summary="Портрет игрока.",
        findings_explained=[
            FindingExplained(
                metric=metric,
                explanation=explanation,
                evidence_frames=frames if frames is not None else [105],
                confidence=confidence,
            )
        ],
        drills=[DrillSelection(priority=1, drill_id=drill_id, rationale=rationale)],
        caveats=[],
    )
```

Заменить два устаревших drill-теста (`test_drill_success_criterion_numbers_not_checked`, `test_unknown_drill_metric_caught`) на:

```python
def test_unknown_drill_id_caught():
    errors = validate_coach_report(_coach(drill_id="totally_made_up"), _evidence())
    assert len(errors) == 1
    assert "totally_made_up" in errors[0]


def test_drill_metric_without_finding_caught():
    # bias-дрилл валиден по id, но finding bias в _evidence() нет
    errors = validate_coach_report(
        _coach(drill_id="bias_t1_vt_1w4ts_novice"), _evidence())
    assert len(errors) == 1
    assert "bias" in errors[0]


def test_drill_rationale_hu_number_grounded_ok():
    errors = validate_coach_report(
        _coach(rationale="Ошибка держится около 1.349 HU."), _evidence())
    assert errors == []


def test_drill_rationale_fabricated_hu_caught():
    errors = validate_coach_report(
        _coach(rationale="Промах доходит до 8.88 HU."), _evidence())
    assert any("8.88" in e for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_validate.py -q`
Expected: FAIL — старый код проверяет `drill.target_metric`, которого в `DrillSelection` нет (AttributeError), и новых тестов ещё нет.

- [ ] **Step 3: Write minimal implementation**

В `coach/validate.py` добавить импорт вверху:

```python
from coach.drill_catalog import get_catalog_drill
```

Заменить блок дриллов в конце `validate_coach_report` (строки ~152-158):

```python
    for drill in coach.drills:
        where = f"дрилл '{drill.drill_id}'"
        cd = get_catalog_drill(drill.drill_id)
        if cd is None:
            errors.append(f"{where} отсутствует в каталоге движка")
        elif cd.metric not in findings_by_metric:
            errors.append(
                f"{where} лечит metric '{cd.metric}', которого нет среди findings"
            )
        errors.extend(_check_hu_numbers(drill.rationale, numbers_known, where))
    return errors
```

Обновить докстроку модуля (строки 4-8): критерий теперь строит движок, VLM отдаёт только `rationale`; проверяется `drill_id` по каталогу.

- [ ] **Step 4: Run drill tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_validate.py -q -k "drill"`
Expected: PASS для новых drill-тестов.

- [ ] **Step 5: Мигрировать golden-фикстуры**

Голден-тесты `test_golden_*` грузят `reports/coach_*.json` в `CoachReport(**...)` — их `drills` в старой форме больше не парсятся. Открыть каждый файл и заменить массив `"drills"`: на каждый старый дрилл — объект `{"priority", "drill_id", "rationale"}`, где:
- `drill_id` = tier-1 id из каталога для метрики старого `target_metric` (маппинг: `consistency`→`consistency_t1_vt_ww5t_novice`, `bias`→`bias_t1_vt_1w4ts_novice`, `correction`→`correction_t1_vt_pasu_novice`, `placement`→`placement_t1_range_preaim_walk`);
- `rationale` = осмысленное обоснование из старого текста дрилла, **без HU-чисел, которых нет в соответствующем evidence-JSON** (безопаснее — качественная формулировка без цифр).

Проверить, что метрика выбранного `drill_id` присутствует среди `findings` того же evidence-файла (`reports/friend_clip3.json` / `reports/author_output_clip.json`); если старый дрилл ссылался на метрику без finding — выбрать существующую.

- [ ] **Step 6: Run full validate suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_validate.py -q`
Expected: PASS (включая `test_golden_friend_b1_response_passes_clean` и `test_golden_author_b1_response_passes_clean`).

- [ ] **Step 7: Commit**

```bash
git add coach/validate.py tests/test_coach_validate.py reports/coach_friend_clip3.json reports/coach_author_output_clip.json
git commit -m "feat(coach): валидатор сверяет drill_id по каталогу + groundedness rationale"
```

---

### Task 4: Промпт — меню каталога + правила выбора

**Files:**
- Modify: `coach/prompt.py` (`SYSTEM_PROMPT` правила 4 и блок «ТРЕНИРОВОЧНЫЙ ПЛАН»; `build_user_text` — инжект меню)
- Test: `tests/test_coach_prompt.py` (добавить тесты; существующие не ломать)

**Interfaces:**
- Consumes: `coach.drill_catalog.menu_for_prompt`.
- Produces: `build_user_text(report, frame_numbers)` содержит меню каталога; `SYSTEM_PROMPT` требует выбирать `drill_id` из меню и не изобретать упражнения/числа.

- [ ] **Step 1: Write the failing test**

Добавить в `tests/test_coach_prompt.py`:

```python
from coach.drill_catalog import menu_for_prompt
from coach.prompt import SYSTEM_PROMPT, build_user_text


def test_user_text_includes_catalog_menu():
    text = build_user_text({"findings": []}, frame_numbers=[])
    assert "consistency_t1_vt_ww5t_novice" in text
    assert menu_for_prompt() in text


def test_system_prompt_forbids_inventing_drills():
    assert "drill_id" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_prompt.py -q -k "catalog or invent"`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

В `coach/prompt.py` заменить правило 4 в `SYSTEM_PROMPT`:

```
4. Каждый дрилл в drills — это ВЫБОР из меню каталога: укажи drill_id из \
приложенного меню, приоритет и rationale (почему именно он). ЗАПРЕЩЕНО \
изобретать упражнения, названия, дозировки и числовые критерии — название, \
платформу, дозу и измеримый критерий успеха подставит движок. В rationale \
не выдумывай HU-числа: допустимы только числа из evidence-JSON.
```

Заменить блок «ТРЕНИРОВОЧНЫЙ ПЛАН»:

```
ТРЕНИРОВОЧНЫЙ ПЛАН: выбери 2–4 дрилла из меню каталога (по одному на \
проблему). Для каждого укажи drill_id, priority (1 — самое важное) и \
rationale. Сначала лечи диагнозы, потом гипотезы. Числовой критерий успеха \
и дозу считает движок — их придумывать не нужно.
```

Добавить импорт и инжект меню в `build_user_text`:

```python
from coach.drill_catalog import menu_for_prompt
```

В `build_user_text` перед финальным `parts.append("Составь коучинг-отчёт...")`:

```python
    parts.append(menu_for_prompt())
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_prompt.py -q`
Expected: PASS (новые + существующие).

- [ ] **Step 5: Commit**

```bash
git add coach/prompt.py tests/test_coach_prompt.py
git commit -m "feat(coach): меню каталога в промпте, VLM выбирает drill_id а не изобретает"
```

---

### Task 5: Сборка финального плана в пайплайне и офлайн-CLI

**Files:**
- Modify: `backend/services/analysis_pipeline.py:126-142` (`_run_coach`)
- Modify: `coach_cli.py:63-72` (запись финальных дриллов)
- Test: `tests/test_analysis_pipeline.py` (проверить сборку финальных дриллов), `tests/test_coach_cli.py` (финальные дриллы в выводе)

**Interfaces:**
- Consumes: `coach.drill_catalog.finalize_plan`, `report["findings"]`.
- Produces: `coach_report` dict, где `drills` — список финальных `Drill` (name/platform/dose/tier/criterion), `caveats` дополнены `extra_caveats`.

- [ ] **Step 1: Write the failing test**

В `tests/test_analysis_pipeline.py` добавить тест (использует инжектируемый `coach_client`, отдающий `DrillSelection`). Опереться на существующие фикстуры файла; минимальный стаб-коуч:

```python
from coach.schema import CoachReport, DrillSelection, FindingExplained


class _SelectionCoach:
    """Стаб-коуч: возвращает DrillSelection, как настоящий VLM после Task 1."""
    def generate(self, report, frame_paths, feedback=None):
        metric = report["findings"][0]["metric"]
        drill_id = {"placement": "placement_t1_range_preaim_walk",
                    "consistency": "consistency_t1_vt_ww5t_novice",
                    "bias": "bias_t1_vt_1w4ts_novice",
                    "correction": "correction_t1_vt_pasu_novice"}[metric]
        return CoachReport(
            summary="ок",
            findings_explained=[FindingExplained(
                metric=metric, explanation="ок",
                evidence_frames=[], confidence=report["findings"][0]["confidence"])],
            drills=[DrillSelection(priority=1, drill_id=drill_id, rationale="ок")],
            caveats=[])


def test_pipeline_assembles_final_drill_from_catalog(tmp_path, monkeypatch):
    # Собрать минимальный прогон через run_pipeline с detector-стабом,
    # как в существующих тестах файла; проверить форму coach_report["drills"].
    # (Опереться на уже имеющиеся фикстуры detector/видео в этом файле.)
    ...
    # После прогона:
    # drill = result.coach_report["drills"][0]
    # assert "name" in drill and "criterion" in drill
    # assert drill["target_metric"] == <ожидаемая метрика>
```

> Реализатору: посмотреть, как существующие тесты `test_analysis_pipeline.py` строят `detector` и вызывают `run_pipeline`, и переиспользовать тот же паттерн; ключевые ассерты — что `coach_report["drills"][0]` содержит `name`, `dose`, `tier`, `criterion` (то есть финальный `Drill`, а не `DrillSelection`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_analysis_pipeline.py -q -k "assembles_final_drill"`
Expected: FAIL — сейчас `_run_coach` кладёт сырые `DrillSelection` (`drills[0]` без `name`).

- [ ] **Step 3: Write minimal implementation**

В `backend/services/analysis_pipeline.py` заменить хвост `_run_coach` (после успешного `run_coach_validated`):

```python
def _run_coach(coach_client, report: dict, frame_paths: Sequence,
               config: PipelineConfig):
    """Любая ошибка коуча -> деградация coach_failed, движок не теряется."""
    from coach.drill_catalog import finalize_plan
    from coach.validate import run_coach_validated
    try:
        client = coach_client
        if client is None:
            from coach.client import CoachClient
            client = CoachClient()
        result = run_coach_validated(
            client, report, list(frame_paths)[: config.coach_max_images])
    except Exception as exc:                      # noqa: BLE001 — деградация
        logger.exception("коуч упал, отдаём частичный результат")
        return None, [f"коуч упал: {exc}"], 0, True
    if result.coach_report is None:
        return None, result.errors, result.attempts, result.coach_failed
    coach_dict = result.coach_report.model_dump()
    plan = finalize_plan(result.coach_report.drills, report.get("findings", []))
    coach_dict["drills"] = [d.model_dump() for d in plan.drills]
    coach_dict["caveats"] = coach_dict["caveats"] + plan.extra_caveats
    return coach_dict, result.errors, result.attempts, result.coach_failed
```

- [ ] **Step 4: Run pipeline test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_analysis_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Обновить офлайн-CLI**

В `coach_cli.py` заменить запись (строки ~63-72), чтобы офлайн-вывод тоже содержал финальные дриллы:

```python
    from coach.drill_catalog import finalize_plan

    coach_report = result.coach_report
    plan = finalize_plan(coach_report.drills, report.get("findings", []))
    out_doc = coach_report.model_dump()
    out_doc["drills"] = [d.model_dump() for d in plan.drills]
    out_doc["caveats"] = out_doc["caveats"] + plan.extra_caveats

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CoachReport записан: {out_path} (попыток: {result.attempts})")
    print(f"Дриллов: {len(out_doc['drills'])}, "
          f"объяснений: {len(coach_report.findings_explained)}, "
          f"оговорок: {len(out_doc['caveats'])}")
    return 0
```

- [ ] **Step 6: Run CLI + full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_cli.py tests/test_analysis_pipeline.py -q`
Expected: PASS. Если `test_coach_cli.py` завязан на старую форму дриллов — обновить его ассерты на финальный `Drill` (наличие `name`/`criterion`).

- [ ] **Step 7: Commit**

```bash
git add backend/services/analysis_pipeline.py coach_cli.py tests/test_analysis_pipeline.py tests/test_coach_cli.py
git commit -m "feat(pipeline): сборка финального плана из каталога после валидации коуча"
```

---

### Task 6: Frontend DrillTable — tier-бейдж, rationale, готовый критерий

**Files:**
- Modify: `frontend/src/components/report/DrillTable.js`

**Interfaces:**
- Consumes: `drill.{priority,name,platform,tier,dose,target_metric,rationale,success_criterion}` (финальный `Drill` из бэкенда).

- [ ] **Step 1: Обновить рендер таблицы**

`success_criterion` уже приходит готовой строкой от движка; добавить tier-бейдж рядом с названием и `rationale` под ним. «Главный дрилл» (priority 1) уже наверху — таблица сортируется по `priority`. Заменить `<td className="drill-name">`:

```jsx
                <td className="drill-name">
                  {drill.name}
                  {drill.tier != null && (
                    <span className="chip chip-tier">tier {drill.tier}</span>
                  )}
                  {drill.rationale && (
                    <div className="drill-rationale">{drill.rationale}</div>
                  )}
                </td>
```

Ключ строки сделать стабильным по `drill_id`:

```jsx
              <tr key={drill.drill_id ?? `${drill.priority}-${drill.name}`}>
```

- [ ] **Step 2: Проверить сборку фронта**

Run:
```powershell
cd frontend
npm run build
```
Expected: сборка без ошибок (нет обращений к удалённым полям).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/report/DrillTable.js
git commit -m "feat(frontend): tier-бейдж и rationale в таблице дриллов"
```

---

### Task 7: Полный прогон и финальная проверка

- [ ] **Step 1: Прогнать весь backend-набор**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. Особое внимание — `test_coach_schema.py`, `test_coach_validate.py`, `test_drill_catalog.py`, `test_coach_prompt.py`, `test_analysis_pipeline.py`, `test_coach_cli.py`.

- [ ] **Step 2: Проверить, что нет забытых ссылок на старую схему дрилла**

Run: `.\.venv\Scripts\python.exe -m pytest -q` — уже покрывает; дополнительно grep по `success_criterion=` и `Drill(` в тестах/коде на предмет старой формы (позиционные `name/platform/dose` без `drill_id/tier/criterion`).

- [ ] **Step 3: Финальный коммит (если остались правки)**

```bash
git add -A
git commit -m "test: зелёный прогон Фазы 1 — каталог дриллов"
```

---

## Данные Voltaic S5 (источник: evxl.app, скриншоты пользователя 2026-07)

Core-семейства и пороги рангов (верхний ранг тира = «закрыть тир»):

| Метрика | Семейство | Novice (iron/bronze/silver/**gold**) | Intermediate (plat/dia/jade/**master**) | Advanced (gm/nova/astra/**celestial**) |
|---|---|---|---|---|
| consistency | ww5t | 990/1090/1190/**1290** | 1310/1400/1490/**1560** | 1510/1610/1720/**1860** |
| bias | 1wNts | 1w4ts 820/915/1010/**1110** | 1w3ts 1120/1220/1300/**1380** | 1w2ts 1320/1420/1520/**1620** |
| correction | Pasu | 555/660/745/**800** | 770/850/930/**980** | 910/1020/1110/**1240** |

Резерв Фазы 2C (трекинг-supplementary, пороги есть на скриншотах, вносятся при реализации 2C): precise `PGT`/`Snake Track`, reactive `Aether`/`Ground`, control `Raw Control`/`Controlsphere`. Второй динамический дрилл correction (`Popcorn`) — опционально при желании.

## Self-Review

**Spec coverage (drill-catalog-design):**
- `coach/drill_catalog.py` (CatalogDrill, CriterionRule, каталог, assemble_drill) → Task 2. ✅
- `schema.py` DrillSelection + сборка → Task 1 + Task 5. ✅
- SuccessCriterion из values, сборка после парса → Task 2 (build_criterion) + Task 5. Примечание: спек предлагал `report.py`, но сборка требует распарсенный VLM-выход, поэтому она в пайплайне после парса — принцип «числа движка» соблюдён (критерий детерминирован из values). ✅
- `validate.py` drill_id↔каталог↔finding, снять number-check с критерия → Task 3. ✅
- `prompt.py` меню + правила → Task 4. ✅
- Правило урезки плана + CTA → Task 2 (`finalize_plan`), интеграция Task 5. ✅
- Frontend DrillTable → Task 6. ✅
- Тесты (каталог, критерии на реальных values, валидатор, урезка) → Task 2, 3. ✅
- Принятые решения: Вариант A (Task 1), нет `tier`/`dose_override` в selection (Task 1), первый клип tier 1 = меню только t1 (Task 2), стабильный неймспейс drill_id (Task 2). ✅
- Каталог = **Voltaic S5** (подтверждён пользователем): consistency→ww5t, bias→1wNts, correction→Pasu; пороги рангов записаны в `rank_thresholds`. ✅

**Осознанно вне Фазы 1 (отложено, не пропущено):** обогащение `correction` фаз-метриками флика, `drill_progress`, трекинг-supplementary, Voltaic/KovaaK's API — это Фаза 2. Трекинг/Popcorn в каталог Фазы 1 не заводим: их id добавятся в Фазе 2C без переименования существующих (decision 5 не нарушается — добавление ≠ переименование).

**Placeholder scan:** Task 3 Step 5 (миграция golden-фикстур) и Task 5 Step 1 (тест пайплайна) требуют чтения существующих файлов по месту — это привязка к неизвестному заранее содержимому; точные правила подстановки заданы.

**Type consistency:** `DrillSelection{priority,drill_id,rationale}`, `SuccessCriterion{metric,value_key,comparator,target,baseline,text}`, `Drill{...,tier,rationale,criterion}`, `CatalogDrill{drill_id,name,platform,tier,metric,dose,instruction,rank_thresholds}`, `finalize_plan(selections,findings)->FinalizedPlan{drills,extra_caveats}` — согласованы между Task 1/2/3/5. drill_id S5 согласованы во всех тасках (Task 1/2/3/4/5).
