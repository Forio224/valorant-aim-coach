# Фаза 3: валидность измерения — атрибуция цели по намерению + гейт пре-айма — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (свежий имплементер на задачу + task-ревью после каждой + финальное whole-branch ревью). Steps используют `- [ ]`.

**Goal:** Убрать два дефекта движка, тихо меряющих не то, что заявлено: (A1) подмена цели между кадрами в `consistency`/`bias` (смена врага под прицелом = «разброс механики»); (A3) пре-айм считает неотстреливаемые появления у края экрана. Плюс переезд ядра геометрии из CLI `aim_metrics.py` в `engine/geometry.py` и версионирование методики (`METRICS_VERSION`).

**Source spec (contract):** `docs/superpowers/specs/2026-07-15-engine-measurement-validity-design.md`. Формулы, пороги и тест-кейсы — оттуда ВЕРБАТИМ. Этот план — декомпозиция «Порядка работ» спеки (7 шагов) на независимо ревьюируемые задачи с назначением моделей.

**Architecture:**
```
heads_by_frame → segment_episodes → episodes
                                       ↓
                             attribute_targets()        ← НОВЫЙ ШОВ (engine/attribution.py)
                                       ↓
                     поток AttributedSample: 1 трек на кадр
                        ↓             ↓              ↓
                  consistency       bias       profile_store
placement, correction, flick_phase — читают episodes напрямую (по-трековые, не меняются)
```

**Tech Stack:** Python 3, frozen dataclasses, `statistics`, pytest. Runs via `.\.venv\Scripts\python.exe`.

---

## Base & Versioning

- **Ветка от `main` ПОСЛЕ мержа PR #2 (Фаза 2B).** Фаза 3 независима от 2B по логике, но пересекается контрактом версий: 2B оставил `SCHEMA_VERSION="1.1"`; Фаза 3 поднимает → **1.2** (аддитивно). `METRICS_VERSION` (Task 6) — новый контракт, который 2B-фильтр истории (`build_clip_snapshots`/anchor-серии) обязан уважать. Если 2B ещё не смержен на момент старта — согласовать base с пользователем.
- Ветка: `phase3-measurement-validity-impl`.

## Global Constraints

- Python только через `.\.venv\Scripts\python.exe`. Тесты: `.\.venv\Scripts\python.exe -m pytest -q`. `dataset1/` ЕСТЬ в дереве — real-clip тесты гоняются, полный сьют зелёный (~264 на 2B-базе).
- **Числа считает ТОЛЬКО движок; если сигнала в данных нет — движок молчит, а не догадывается.** Детектор видит только головы (не оружие/HP/кто-кого-заметил).
- **Без декодирования видео в метрическом пути** — атрибуция работает по детекциям (оценка камеры по фону сознательно НЕ берётся; видео читает только `evidence_frames`).
- **Переезд геометрии (Task 1) НЕ меняет ни одного числа** — регрессия-гейт: все существующие тесты движка/коуча зелёные без правок; `aim_metrics.py` реэкспортит имена (обратная совместимость импортов).
- **Схема аддитивна → 1.2**, фронт НЕ трогаем (только `npm run build` verify). Новые поля: top-level `target_choices`; в `values` находки `consistency` — `switches`/`contested_frames`/`camera_confidence`; в `placement` — `median_dy_hu`/`total_seen`/`total_gated`.
- **Все новые ручки — НЕКАЛИБРОВАННЫЕ дефолты** (калибровка на `dataset1/` — отдельная будущая задача, как `conf=0.4` на холдауте). Каждую пометить в коде `# некалибр.`. Точные значения (спека, таблица «Ручки»): `INTENT_WINDOW_S=0.05`, `MIN_INTENT_HU_S=8.0`, `SWITCH_MARGIN_HU_S=6.0`, `CONTESTED_MARGIN_HU_S=3.0`, `DWELL_MAX_CAMERA_HU_S=4.0`, `PLACEMENT_MAX_BIRTH_HU=8.0`. Пороги — в секундах / HU-в-секунду (30 и 60 fps сравнимы).
- **Иммутабельность:** все новые носители — `@dataclass(frozen=True)`; входы не мутируем.
- Русскоязычные докстроки, английские идентификаторы.
- **Явно вне скоупа (спека):** гейт живого геймплея (смерть/спектейт/killcam), статистическая честность (автокорреляция дуэльных кадров), шум HU-нормировки, нормативный вердикт о приоритете целей, гейт `correction` по атрибуции, ADS/зум. Не реализовывать.

---

## Model & Review Strategy (экономия токенов)

| Task | Суть | Модель имплементера | Причина |
|---|---|---|---|
| 1 | Переезд геометрии в `engine/geometry.py` + реэкспорт | **haiku** | Механический move, числа не меняются, регрессия-гейт ловит ошибки |
| 2 | `engine/attribution.py` — алгоритм атрибуции | **sonnet** | Субтильное ядро (камера→намерение→выбор/гистерезис/contested); нужна аккуратность |
| 3 | Проводка consistency/bias/profile_store на AttributedSample; удалить `samples_from_heads` | **sonnet** | Мульти-файловая интеграция, ломает существующий поток |
| 4 | `target_choices` в отчёт + SCHEMA_VERSION→1.2 | **haiku** | Аддитивный блок по готовым `TargetChoice` из Task 2 |
| 5 | Гейт пре-айма (placement) | **sonnet** | Меняет определение метрики + анти-survivorship логика |
| 6 | `METRICS_VERSION` + фильтр агрегации profile_store | **sonnet** | Кросс-фазовый контракт с 2B, версионная фильтрация |
| 7 | Зелёный прогон + verify фронта | **haiku** | Только запуск команд |

**Ревью:** масштабировать под диф. Task 1/4/7 (механические/аддитивные) → **haiku**-ревью. Task 2/3/5/6 (алгоритм/интеграция) → **sonnet**-ревью. **Финальное whole-branch ревью → opus** (Task 2 — алгоритмическое ядро, кросс-коммитные контракты AttributedSample↔потребители и METRICS_VERSION↔2B). Фиксы — один субагент на все findings задачи, не по-findings.

**Ключевой контроллерский приём:** передавать бриф/интерфейсы/диф файлами (`scripts/task-brief`, `scripts/review-package`), не пастить в промпт; держать ledger в `.superpowers/sdd/progress.md`.

---

### Task 1: Переезд ядра геометрии в `engine/geometry.py`

**Suggested model:** haiku (чистый move; регрессия-гейт — страховка).

**Files:**
- Create: `engine/geometry.py` — перенести из `aim_metrics.py`: `Head`, `FrameSample`, `sample_frame`, `pick_target`, `MIN_HEAD_PX`, `DEFAULT_DUEL_HU`, `AimPassport`, `compute_passport` (весь блок ядра, НЕ адаптеры источников).
- Modify: `aim_metrics.py` — удалить перенесённые определения, добавить `from engine.geometry import Head, FrameSample, sample_frame, pick_target, MIN_HEAD_PX, DEFAULT_DUEL_HU, AimPassport, compute_passport` (реэкспорт: существующие `from aim_metrics import ...` и тесты не ломаются). Оставить в `aim_metrics.py` только CLI + адаптеры (`iter_gt_samples`, `iter_yolo_samples`).
- Test: `tests/test_geometry.py` (новый — smoke на импорт из нового места) + регрессия ВСЕГО сьюта.

**Interfaces produced:** `engine.geometry.*` (все имена ядра). Consumes: ничего нового.

- [ ] **Step 1:** Найти в `aim_metrics.py` точные границы блока ядра (grep `class Head`, `class FrameSample`, `def sample_frame`, `def pick_target`, `MIN_HEAD_PX`, `DEFAULT_DUEL_HU`, `class AimPassport`, `def compute_passport`). Убедиться, что шесть `engine/`-модулей импортят эти имена из `aim_metrics` (grep `from aim_metrics import` по `engine/`) — после реэкспорта они продолжат работать; в идеале переключить их на `engine.geometry` в этом же таске (по желанию, но реэкспорт обязателен как минимум).
- [ ] **Step 2 (RED-эквивалент):** написать `tests/test_geometry.py` — импорт каждого имени из `engine.geometry`, конструирование `FrameSample`/`Head`, вызов `sample_frame`/`pick_target` на синтетике; сверить, что `aim_metrics.<name>` — тот же объект (`is`). Запуск → FAIL (модуля нет).
- [ ] **Step 3:** создать `engine/geometry.py`, перенести блок ВЕРБАТИМ (ни один литерал/формула не меняется). Добавить реэкспорт-импорт в `aim_metrics.py`.
- [ ] **Step 4 (регрессия-гейт):** `.\.venv\Scripts\python.exe -m pytest -q`. Expected: тот же ~264 passed что и на базе; НОЛЬ изменившихся чисел. Любое новое падение = ошибка переезда.
- [ ] **Step 5:** Commit — `refactor(engine): вынести ядро геометрии в engine/geometry.py (реэкспорт, числа не меняются)`.

---

### Task 2: `engine/attribution.py` — атрибуция цели по намерению

**Suggested model:** sonnet (алгоритмическое ядро фазы).

**Files:**
- Create: `engine/attribution.py`.
- Test: `tests/test_attribution.py` (синтетика, без видео/БД — по образцу существующих тестов движка).

**Interfaces produced (спека §Контракты — ВЕРБАТИМ):**
```python
@dataclass(frozen=True)
class AttributedSample:
    frame_idx: int
    track_id: Optional[int]        # None = contested
    dx_hu: float; dy_hu: float; radial_hu: float
    head_height_px: float
    switch: bool                   # первый кадр новой цели
    contested: bool

@dataclass(frozen=True)
class TargetChoice:
    track_id: int; from_frame: int; to_frame: int
    chosen_at_radial_hu: float
    head_height_px: float          # прокси дистанции
    lateral_speed_hu_s: float      # прокси стрейфа (по residual, не камере)
    switch_cost_frames: Optional[int]

@dataclass(frozen=True)
class AttributionResult:
    samples: Tuple[AttributedSample, ...]
    choices: Tuple[TargetChoice, ...]
    switches: int; contested_frames: int
    camera_confidence: str         # diagnosis | hypothesis | insufficient

def attribute_targets(episodes: Sequence[Episode], ctx: ClipContext,
                      duel_hu: float = DEFAULT_DUEL_HU) -> AttributionResult
```

**Алгоритм (спека §Компонент 1 — реализовать точно):**
- **Оценка камеры (кадр N по трекам, живым на N и N−1):** `camera_shift = median(смещений голов в px)` (медиана, не среднее — один стрейфер не утащит). При 1 голове оценка не нужна (она и есть цель). При ровно 2 головах медиана=среднее → стрейф пролезает наполовину → отражается в `camera_confidence`.
- **Намерение** головы в позиции `p` (отн. центра) при камерном сдвиге `c`: `intent(h) = (|p| − |p + c|) / head_height_px * fps` (HU/с, закрытых КАМЕРОЙ; собственное движение врага в `c` не входит). Накапливать по окну `INTENT_WINDOW_S`.
- **Правило выбора (спека §Правило выбора):** цели нет → кандидат с max намерением > `MIN_INTENT_HU_S` (если камера стоит и намерения нет → ближайшая, вырожденный статический случай); цель есть и видна → держим, пока другой не опередит на `SWITCH_MARGIN_HU_S` → переключение НЕМЕДЛЕННО; цель исчезла → ближайшая по намерению/ближайшая; удержание → камера почти стоит (`< DWELL_MAX_CAMERA_HU_S`) и цель в дуэльной зоне → держим; спор → два кандидата в пределах `CONTESTED_MARGIN_HU_S` при отсутствии текущей цели ЛИБО камеру не оценить при 2+ головах → кадр `contested` (track_id=None), из механических статистик исключается, но СЧИТАЕТСЯ.
- **`camera_confidence`:** 3+ головы → diagnosis; 2 → hypothesis; 1 → insufficient (не нужна).
- **Гистерезис защищает от неоднозначности, не от намерения:** решительный флик к другой голове = большое камерное намерение → переключает сразу; дребезг «на полпикселя ближе» камерного намерения не создаёт → цель не двигает.
- **`TargetChoice`:** `lateral_speed_hu_s` — по residual (движение врага за вычетом камеры), не по камере; `switch_cost_frames` — кадров от переключения до входа в дуэль (`None` если не вошла).
- `consistency`/`bias` потребляют `samples` с `track_id is not None`.

**Все ручки — с дефолтами в сигнатуре/константах модуля, помечены `# некалибр.`; в секундах / HU-с.**

- [ ] **Step 1 (RED):** `tests/test_attribution.py` — тест-кейсы из спеки §Проверка (каждый — синтетические `Episode`/`FrameSample`): фланговый мультикилл (ближний в 2 HU игнор, камера к дальнему в 12 HU → атрибуция уходит за камерой к дальнему — тест на исходный дефект A1); осознанный флик переключает немедленно; дребезг близости НЕ переключает; стрейфящийся враг не крадёт цель (его движение не создаёт намерения); спор помечается и считается; `camera_confidence` 1/2/3+ = insufficient/hypothesis/diagnosis; gt и yolo дают одинаковую атрибуцию на одних треках. Запуск → FAIL (модуля нет).
- [ ] **Step 2:** реализовать `engine/attribution.py`. Если формула/ручка спеки допускает >1 прочтения — СТОП, report NEEDS_CONTEXT (не выдумывать).
- [ ] **Step 3 (GREEN):** `.\.venv\Scripts\python.exe -m pytest tests/test_attribution.py -q` → PASS (все кейсы).
- [ ] **Step 4:** Commit — `feat(engine): attribution — оценка камеры (медиана) → намерение → выбор/гистерезис/contested`.

---

### Task 3: Проводка consistency/bias/profile_store на `AttributedSample`

**Suggested model:** sonnet (мульти-файловая интеграция, ломает поток samples).

**Files:**
- Modify: `backend/services/analysis_pipeline.py` — заменить построение `samples` через `samples_from_heads` (~line 118) на `attribute_targets(episodes, ctx)`; **удалить `samples_from_heads`**. Поток `consistency`/`bias`/`profile_store` кормится `AttributedSample` с `track_id is not None`.
- Modify: `engine/report.py` — `_consistency_finding`/`_bias_finding` принимают отфильтрованный поток; в `values` находки `consistency` добавить `switches`, `contested_frames`, `camera_confidence` (движок честно показывает, сколько кадров было спорных, вместо тихого смешивания врагов).
- Modify: `engine/profile_store.py` — `build_clip_record` на новом потоке.
- Test: `tests/test_analysis_pipeline.py`, `tests/test_report.py`, `tests/test_profile_store.py` — обновить/дополнить.

**Interfaces:** consumes `attribute_targets` (Task 2). Produces: обновлённые `consistency.values` (+3 ключа).

- [ ] **Step 1 (RED):** тест — на клипе с двумя врагами и сменой цели под прицелом `consistency.std_hu` НЕ включает скачок смены цели (сравнить со старым поведением на синтетике: с атрибуцией разброс ниже); `consistency.values` содержит `switches`/`contested_frames`/`camera_confidence`. Запуск → FAIL.
- [ ] **Step 2:** провести поток на `AttributedSample`; удалить `samples_from_heads`; добавить 3 ключа. Грепнуть `samples_from_heads` по всему репо — ноль осиротевших ссылок.
- [ ] **Step 3 (GREEN + регрессия):** `.\.venv\Scripts\python.exe -m pytest tests/test_analysis_pipeline.py tests/test_report.py tests/test_profile_store.py -q` → PASS. Полный сьют — без НОВЫХ падений сверх ожидаемого сдвига чисел consistency/bias (числа МЕНЯЮТСЯ намеренно — обновить эталоны real-clip тестов, если они pin точные значения; задокументировать сдвиг в отчёте).
- [ ] **Step 4:** Commit — `feat(engine): consistency/bias/profile_store на AttributedSample; удалить samples_from_heads`.

> **Кросс-задачный флаг для контроллера:** этот таск МЕНЯЕТ определения `mae_hu`/`std_hu` → это причина `METRICS_VERSION` (Task 6). Убедиться, что Task 6 идёт в той же ветке до мержа.

---

### Task 4: `target_choices` в отчёт + `SCHEMA_VERSION` → 1.2

**Suggested model:** haiku (аддитивный блок по готовым `TargetChoice`).

**Files:**
- Modify: `engine/report.py` — `build_report` кладёт top-level `report["target_choices"]` (список `asdict(TargetChoice)` из `AttributionResult.choices`) — НЕ находкой (у находок критерии/дриллы, здесь вердикта нет и быть не должно; база для будущей нормативной фазы). Поднять `SCHEMA_VERSION` `"1.1"` → `"1.2"`.
- Test: `tests/test_report.py` — дополнить.

**Interfaces:** consumes `AttributionResult.choices` (Task 2), пробрасывается через пайплайн (Task 3).

- [ ] **Step 1 (RED):** тест — `report["target_choices"]` присутствует, каждый элемент имеет поля `TargetChoice`; `report["schema_version"] == "1.2"`. Запуск → FAIL.
- [ ] **Step 2:** добавить блок + бамп версии.
- [ ] **Step 3 (GREEN):** `pytest tests/test_report.py -q` → PASS.
- [ ] **Step 4:** Commit — `feat(report): top-level target_choices (без вердикта) + schema 1.2`.

---

### Task 5: Гейт пре-айма (placement)

**Suggested model:** sonnet (меняет определение метрики + анти-survivorship).

**Files:**
- Modify: `engine/metrics/placement.py` — новая ручка `PLACEMENT_MAX_BIRTH_HU = 8.0  # некалибр.`: в пре-айм идут только появления в пределах N HU от прицела на кадре РОЖДЕНИЯ трека (гейт по дистанции, НЕ по вовлечённости — иначе survivorship bias: гейт «была дуэль» выкинул бы ровно провальный пре-айм). В `values`: `mean_dy_hu` остаётся ключом (не ломаем фронт/`build_criterion` Фазы 1), но считается по отфильтрованному множеству; добавить `median_dy_hu` (устойчив к выбросам), `total_seen`/`total_gated`. `total` (вход `build_criterion`) = `total_gated`.
- Test: `tests/test_placement.py` — дополнить.

**Interfaces:** — (placement по-трековый, не зависит от attribution).

- [ ] **Step 1 (RED):** тесты §Проверка — анти-survivorship: враг, возникший в 5 HU и прозёванный, ЗАСЧИТАН как провал пре-айма; враг в 20 HU через весь экран — отсечён (позиционирование, не пре-айм). `median_dy_hu`/`total_seen`/`total_gated` присутствуют; `total==total_gated`. `_confidence` считается от отфильтрованного числа (пре-айм честно опускается с диагноза до гипотезы на части клипов — ожидаемое следствие, не баг). Запуск → FAIL.
- [ ] **Step 2:** реализовать гейт + новые ключи.
- [ ] **Step 3 (GREEN + регрессия):** `pytest tests/test_placement.py -q` → PASS; `build_criterion` для placement по-прежнему работает (`total`=`total_gated`).
- [ ] **Step 4:** Commit — `feat(engine): гейт пре-айма по дистанции рождения + median_dy_hu/total_seen/total_gated`.

---

### Task 6: `METRICS_VERSION` + фильтр агрегации profile_store

**Suggested model:** sonnet (кросс-фазовый контракт с 2B).

**Files:**
- Create/Modify: `engine/` — константа `METRICS_VERSION` (напр. в `engine/geometry.py` или отдельный `engine/version.py`).
- Modify: `engine/profile_store.py` — `build_clip_record` штампует записи `metrics_version`; записи без поля = версия 1; `aggregate_profile` берёт ТОЛЬКО записи текущей версии, отброшенные называет в `confidence_reason` («клипов по прежней методике: N — в сравнение не входят»).
- Test: `tests/test_profile_store.py` — дополнить.

**Interfaces:** **контракт для Фазы 2B:** `build_clip_snapshots`/anchor-серии обязаны фильтровать историю по `metrics_version` (иначе смена методики Task 3/5 = «прогресс» игрока). Задокументировать в докстроке + в отчёте контроллеру.

- [ ] **Step 1 (RED):** тест — запись без `metrics_version` НЕ входит в агрегат, причина названа в `confidence_reason`; запись текущей версии входит. Запуск → FAIL.
- [ ] **Step 2:** добавить константу + штамп + фильтр.
- [ ] **Step 3 (GREEN):** `pytest tests/test_profile_store.py -q` → PASS.
- [ ] **Step 4:** Commit — `feat(engine): METRICS_VERSION + фильтр агрегации профиля (контракт для 2B-истории)`.

---

### Task 7: Зелёный прогон + verify фронта

**Suggested model:** haiku (только запуск команд, кода не пишет).

- [ ] **Step 1:** `.\.venv\Scripts\python.exe -m pytest -q` — записать сводку. Ожидаемо: числа consistency/bias/placement СДВИНУЛИСЬ (намеренно, Task 3/5); эталоны обновлены; ноль НЕОЖИДАННЫХ падений. Один FastAPI/httpx `StarletteDeprecationWarning` — известный, не падение.
- [ ] **Step 2:** grep `samples_from_heads` по репо — ноль ссылок (подтвердить удаление).
- [ ] **Step 3 (граница «не трогаем фронт»):** `cd frontend ; npm run build` → успех (схема 1.2 аддитивна, `target_choices`/новые `values`-ключи не роняют CRA; при отсутствии node_modules — `npm install`).
- [ ] **Step 4:** финальный коммит если остались правки — `test: зелёный прогон Фазы 3 — валидность измерения`.

---

## Self-Review (spec coverage)

- Компонент 1 (атрибуция: камера-медиана → намерение → выбор/гистерезис/contested, `camera_confidence`, `AttributedSample`/`AttributionResult`/`TargetChoice`) → **Task 2** (полные тест-кейсы §Проверка). ✅
- Компонент 2 (`target_choices` top-level, схема 1.2) → **Task 4**. ✅
- Компонент 3 (гейт пре-айма по дистанции рождения, `median_dy_hu`/`total_seen`/`total_gated`, `total=total_gated`, анти-survivorship) → **Task 5**. ✅
- Компонент 4 (`METRICS_VERSION`, фильтр агрегации, контракт для 2B) → **Task 6**. ✅
- Переезд геометрии (числа не меняются, реэкспорт) → **Task 1**. ✅
- Проводка на `AttributedSample` + `switches`/`contested_frames`/`camera_confidence` + удаление `samples_from_heads` → **Task 3**. ✅
- Границы (фронт verify, схема аддитивна, некалибр. ручки) → **Task 7** + Global Constraints. ✅

**Порядок исполнения (зависимости):** 1 → 2 → 3 → 4 → 5 → 6 → 7. Task 4 зависит от 2 (choices) и 3 (проброс). Task 5/6 независимы от attribution, но идут в той же ветке (числа+версия согласованы до мержа). Task 2 — критический путь (алгоритм); закладывать на него больше времени/ревью.

**Открытые вопросы (из спеки, НЕ блокируют):** калибровка ручек на `dataset1/`; гейт `correction` по атрибуции; нормативная фаза «правильность приоритета» (нужен сигнал об угрозе, которого в детекторе голов нет).

---

## Phase 4 deferred

План Фазы 4 (`docs/superpowers/specs/2026-07-16-engine-input-space-and-severity-design.md`) НЕ пишется здесь: её спека статусом «заблокирован до влития Фазы 3 в код» — ссылается на `engine/geometry.py`, схему 1.2 и `METRICS_VERSION`, появляющиеся ТОЛЬКО в этой фазе. Писать план Фазы 4 после мержа Фазы 3, взяв main как базу.
