# Дизайн Фазы 2B: петля прогресса на engine-сигнале

**Статус:** УТВЕРЖДЁН по развилкам (2026-07-07, брейншторм-диалог). Зависит от
Фазы 1 (стабильные `drill_id`, `SuccessCriterion` с `baseline`/`target`,
детерминированный `build_criterion`) и Фазы 2A (не пересекается, но обе на ветке
после 2A).
**Дата:** 2026-07-07. **Область:** `engine/` (хелпер критерия + `drill_progress`),
`coach/` (структурное поле прогресса + guard), `backend/` (инжектируемый
`history_provider`). **Фронт НЕ трогаем** (см. §Границы).
**Родитель:** [2026-07-05-phase2-progress-loop-design.md](2026-07-05-phase2-progress-loop-design.md)
(полная Фаза 2; здесь — под-фаза 2B, компоненты B/C/F без внешнего API).

## Проблема

Фаза 1 назначает дрилл и записывает `SuccessCriterion` с `baseline`. История
метрик по клипам копится (`AnalysisSession.evidence_report`/`coach_report`,
`engine/profile_store.py`), но не отвечает на главный вопрос удержания:
**«сдвинулась ли метрика после совета?»**. 2B замыкает петлю на **уже имеющемся**
engine-сигнале, без KovaaK's API и Steam ID (это 2C).

## Управляющий принцип (сохранён и усилен)

Движок считает КАЖДОЕ число (дельту, direction, confidence); VLM только
формулирует направление и **НЕ** утверждает каузальность («дрилл сработал»):
адхеренс и конфаундеры неизвестны. 2B добавляет числа движка и **механический
guard** против выдуманного направления/каузальности.

---

## Объём 2B (решение по развилке)

Берём компоненты B (секция `drill_progress`), C (чтение истории), F (язык
динамики + запрет каузальности) + **кавеат неопределённого порядка клипов** в
выдаче. **Откладываем:** UI-панель §G → **2C** (чтобы HU-тренд и Voltaic-ранг
собрать одной панелью разом); поле «дата съёмки» + DB-миграция → **UI-спек**
(`order_uncertain` пока константа `True`).

**Почему F обязателен вместе с B/C:** как только `drill_progress` (дельты) попадает
в evidence-JSON, коуч его видит (клиент получает весь отчёт). Без guard `validate.py`
не знает про запрет каузальности → коуч спокойно скажет «твой дрилл сработал» —
ровно запрещённая конструкция. B/C без F — не самая маленькая плитка, а самая
дырявая. Guard едет вместе с дельтами.

---

## Компонент 1 — общий хелпер критерия (`engine/`), анти-цикл

**Проблема, которую он закрывает:** и `build_criterion` (Фаза 1, `coach/`), и новый
`compute_drill_progress` (`engine/`) должны нормировать сырое значение метрики в
«baseline-space» (bias → `abs()`+округление; consistency → округление; placement →
`int(below)`; correction → счётчик худшей оси) и знать `comparator`. Дублировать
эту нормировку в двух модулях = она разъедется при первой доменной правке каталога.

**Решение (жёсткое требование по слоям):** числовое ядро живёт в `engine/` и
возвращает **нейтральный dict**, НЕ `SuccessCriterion`:

```python
# engine/metrics/criterion.py  (новый; или рядом — но в engine/)
def compute_metric_criterion(metric: str, values: dict) -> Optional[dict]:
    # {value_key, comparator, target, baseline, directional_meaningful}
```
- `baseline` = значение в baseline-space (нормированное).
- `comparator` ∈ {`"<"`, `"count_le"`, `"direction"`}.
- `directional_meaningful=False` для вырожденца correction (`count==0` →
  `value_key="flicks_analysed"` — это объём, не качество).

`coach/drill_catalog.build_criterion` становится тонкой обёрткой: зовёт
`compute_metric_criterion`, добавляет человеческий `text`, возвращает
`SuccessCriterion`. Поведение `build_criterion` **не меняется** (регрессия-тест).

**Почему нейтральный dict, а не `SuccessCriterion`:** `SuccessCriterion` живёт в
`coach.schema`. Если engine-хелпер вернёт его — появится ребро `engine → coach.schema`,
а `coach.drill_catalog → engine.helper → coach.schema` = **цикл**; плюс инвертируются
слои (`engine` — нижний, стоит автономно под CLI `aim_metrics.py`). Подтверждено:
сегодня **ноль** импортов `engine → coach`; `aim_metrics.py` импортит только
`engine`. Хелпер обязан оставить движок автономным — это тот же инвариант, что
«движок без БД».

Плюс `normalize(value_key, raw) -> float` (тот же модуль) — применяется к сырому
значению текущего клипа под **фиксированным anchor-`value_key`**. **Обязана
применять ТОТ ЖЕ per-`value_key` трансформ, что `compute_metric_criterion` кладёт в
`baseline`, ВКЛЮЧАЯ округление:** `*_bias_hu` → `abs()` затем `_r` (до 3 знаков, как
в каталоге); `mae_hu` → `_r`; счётчики (`below`, `x_overshoots`…) → `int`. Иначе
`anchor_value` (округлён через `baseline`) и `current_value` (через `normalize`)
живут в чуть разных пространствах → флипы на границах `flat`/резолюции. Одна
нормировка везде — anchor и current в идентичном пространстве.

## Компонент 2 — секция `drill_progress` (движок)

`compute_drill_progress(findings, drill_history) -> list`, чистая функция
(`engine/metrics/`), вызывается `build_report` и кладёт **top-level**
`report["drill_progress"]` (не внутрь finding-а).

**Инжектируемый вход** — снимок на КАЖДЫЙ прошлый клип (не разрежённые записи
назначений):
```
drill_history: Sequence[ClipSnapshot]
ClipSnapshot = {clip_time, clip_id, assignments:{metric: drill_id}, findings:{metric:{values, confidence}}}
```
`assignments` = `{метрика: drill_id}` для метрик, получивших дрилл на том клипе
(«флагнута» = ключ в `assignments`; `drill_id` нужен для `drill_id` выходной записи
= самый свежий назначенный). Упорядочен по возрастанию `clip_time` (сортирует
пайплайн). `build_report` получает `drill_history: Sequence = ()`
(аддитивный дефолт → существующие вызовы/CLI/тесты не ломаются; CLI подаёт `[]`).

**Ретроспективный active-set (решение по развилке):** репортим одну запись на
**каждую метрику с открытой (неразрешённой) серией в истории**. `baseline_set`
**убран** (мёртвый код при ретроспективном active-set — новые дриллы и так уезжают
свежим `coach_report`). Первый клип / нет серии → запись не эмитится.

**Серия и anchor (Баг A — разрыв по резолюции, не по отсутствию дрилла):**
для метрики M с ≥1 флагом в истории:
1. **anchor** = первый флагнутый клип текущего *неразрешённого* прогона.
   **Резолюция** прогона — клип, где нормированное значение M удовлетворяет
   `comparator` anchor-а против его `target` (`<`/`count_le`), **И** confidence
   этого клипа `≥ hypothesis` (не `insufficient`). После резолюции серия
   рестартует со следующего флага (зажившая-и-вернувшаяся слабость → новый anchor).
   Слабость, просто выпавшую из назначений (топ-2-трим Фазы 1 или невыбор VLM),
   но неразрешённую — anchor **держит**.
   **Origin anchor-значений (снять двусмысленность):** `value_key`, `comparator`,
   `directional_meaningful` фиксируются `compute_metric_criterion(M, anchor.findings[M].values)`
   на КЛИПЕ-anchor (для correction здесь же выбирается худшая ось). `anchor_value` =
   `baseline` этого же вызова; `anchor_conf` = `anchor.findings[M].confidence`. Далее
   `value_key` держится фиксированным на всю серию (даже если позже худшая ось иная —
   «та же ось, другая проблема» уже разведено, т.к. `value_key` axis+kind-специфичен).
2. **correction — исключение:** `comparator="direction"`, `target=None` → надёжного
   события «решено» нет → серия **не рвётся никогда** в 2B, anchor = первый флаг.
   (`value_key` уже axis+kind-специфичен: `x_overshoots ≠ x_undershoots`.) Честность
   несут `min`-confidence + прокси-кавеат, не выдуманные разрывы.
3. **current** = анализируемый сейчас клип:
   `current_value = normalize(value_key, findings[M].values[value_key])`.
4. `delta = _r(current_value − anchor_value)` — **`_r` до baseline-точности (3 знака),
   НЕ голый `round()` до целого** (иначе суб-HU сигнал 0.2/0.6 HU схлопнется в 0/1);
   для счётчиков разность целочисленная. Оба конца уже в одном нормированном
   пространстве (см. `normalize` выше), поэтому граница точна и симметрична.
   `direction` из `comparator` (все `value_key` — «меньше лучше»:
   `improved`/`regressed`/`flat` по знаку; `flat` = дельта `== 0` после `_r`;
   `directional_meaningful=False` → пропуск как `insufficient`, НЕ фейковый `improved`);
   `confidence = min(anchor_conf, current_conf)` по порядку
   `insufficient < hypothesis < diagnosis`.

**Резолюция-гейт `≥ hypothesis` (тот же принцип, третий раз):** `insufficient` =
сэмплов не хватает верить значению → не хватает и верить в резолюцию. Шумный клип
под target НЕ сбрасывает anchor. Не поднимать до `diagnosis` в 2B: слабости
флагаются на `hypothesis`; флагать по hypothesis, а разфлагивать по diagnosis =
храповик (anchor'ы залипают). Строгий `diagnosis`-гейт → 2C (тир-прогрессия).

**Композиция резолюции с current:** current под target, но `insufficient` → НЕ
`resolved_now`, а обычная дельта с `confidence=insufficient` (через `min`). Не
празднуем «решено!» на мусоре — выходит само.

**Запись выхода:**
```
{metric, drill_id, value_key, comparator, anchor_value, anchor_clip_id,
 current_value, delta, direction, confidence, series_len, resolved_now, order_uncertain}
```
- `drill_id` = самый свежий назначенный для M (actionable — что делать дальше);
  provenance несёт `anchor_clip_id`. В 2B тир статичен → anchor'ный и свежий
  `drill_id` совпадают; расхождение только с 2C (тир-бамп = резолюция = сброс
  anchor'а → снова синхрон). `most-recent` forward-compatible.
- `resolved_now` = current удовлетворил target (для «решено на этом клипе»).
- `series_len` = на скольких клипах истории держится дельта.
- `order_uncertain` = константа `True` в 2B (только `created_at` = время загрузки).

**Детерминированный порядок списка (иначе флейки + дёрганый UI):** сортировка по
каноническому порядку `CORE_METRICS` (`placement, consistency, bias, correction`) —
консистентно с порядком findings в отчёте, без запекания UX-политики в числовой
слой (приоритизацию «regressed первыми» делает UI-слой в 2C). Зафиксировать тестом.

## Компонент 3 — guard коуча (промпт + валидатор)

**Обязательно в любом виде:**
- **Пул чисел** `validate._known_numbers` += значения `drill_progress`
  (`anchor_value`, `current_value`, `delta`). Иначе процитированная дельта
  «−0.6 HU» не найдётся в пуле → `_check_hu_numbers` отклонит валидную дельту.
  `_check_hu_numbers` сравнивает по модулю → знаковую дельту кладём как есть
  (заземлит и `−0.6`, и `0.6`).

**Структурное поле (Option 1 — иначе центральное утверждение 2B не заземлено):**
`direction` — новый класс заземляемого утверждения (не число/кадр/confidence-лейбл,
а факт «метрика сдвинулась в сторону D»). «Твоя точность выросла» при движковом
`regressed` — некаузальное, но ложное; из прозы `improved` не извлечь без NLP.
Значит коуч декларирует направление структурно:

```python
# coach/schema.py — новое поле CoachReport
class ProgressExplained(BaseModel):
    metric: str
    direction: Literal["improved", "regressed", "flat"]  # enum, матчится ==
    confidence: Confidence
    explanation: str                                     # проза (грундинг)
# CoachReport += progress_explained: List[ProgressExplained]
```
- `direction` — **enum, матч равенством** против `engine.direction`. Человеческая
  формулировка («движется в нужную сторону» / «вернулась к прошлому уровню») идёт
  в `explanation` (free-text: HU-грундинг + каузальный бан + hedged→no-assertive).
  Не давать `direction` стать прозой — равенство не сойдётся.
- `confidence` матчить против **отдельного `progress_by_metric`** lookup по
  `drill_progress`, **НЕ** против `findings_by_metric`: одна метрика M несёт две
  разные confidence — finding (только текущий клип) и drill_progress
  (`min(anchor, current)`). Переиспользовать findings-lookup = ложные ошибки/пропуски.
- `metric` из `progress_explained`, которого **нет** в `drill_progress` → ошибка
  (коуч не выдумывает прогресс по неотслеживаемой метрике — тот же гейт, что
  «finding отсутствует в отчёте движка» для `findings_explained`).

**Каузальный бан (замечание A — новая ветка, не копипаст):** новый стопворд-класс
(`сработал`, `благодаря (дриллу/тренировке)`, `из-за тренировк*`, `помог(ла) дрилл`,
`эффект дрилла` и т.п.) чекается **явно** на `summary` + `findings_explained` +
`progress_explained.explanation` + `drill.rationale` + `caveats`. Сегодня
`_ASSERTIVE_STOPWORDS_RE` живёт ТОЛЬКО внутри цикла `findings_explained` — `summary`
и `caveats` не защищены даже от утвердительных слов. Поэтому каузальный чек на
`summary` и `caveats` — новая поверхность. Регекс: предпочитать over-block под-block
(ложный блок ловится ретраем, коуч перефразирует; пропущенная каузальность
необратима) — простой word-boundary стопворд-лист приемлем.

**Промпт (`coach/prompt.py`):** правило про `drill_progress` — озвучь *направление*
с учётом `confidence`, дельта-числа только из `drill_progress`, НЕ приписывай
движение дриллу. `hedged→no-assertive` и HU-грундинг переиспользуют существующий код.

## Компонент 4 — пайплайн: инжектируемый `history_provider` (тупой добытчик)

Чтобы `run_pipeline` тестировался без БД и держал инжект-паттерн (детектор,
коуч-клиент уже инжектятся), чтение истории — **новый инжектируемый
`history_provider`**, не прямой DB-вызов в движке/теле пайплайна:
```
history_provider(player_id, exclude_clip_id) -> List[ClipSnapshot]
```
- **Дефолтная реализация (backend):** запрос `AnalysisSession` по `player_id` с
  непустым `evidence_report`; **дедуп по `clip_id`** (свежая сессия побеждает —
  зеркалит идемпотентность `profile_store`: переанализ клипа ≠ новая точка);
  **исключить текущий `clip_id`**; сортировка по `created_at` возр.
  `assignments = {d["target_metric"]: d["drill_id"] for d in coach_report["drills"]}`
  (собранные дриллы несут `target_metric` и `drill_id`); `findings` из `evidence_report`.
- **Сессии `coach_failed` включаем** снимком: (а) провал валидации коуча → есть
  реальные findings, `assignments={}` (метрика может *разрешиться* на клипе
  без дрилла; эндпоинт/резолюция берутся); (б) пустой клип (нет врагов) → findings
  по M нет вообще → снимок инертен (M не эндпоинт/не резолюция, прозрачно пропущен).
- Пайплайн: `history = history_provider(player_id, ctx.clip_id)` →
  `build_report(..., drill_history=history)`. **CLI подаёт `[]`** → `drill_progress=[]`,
  офлайн `aim_metrics.py` жив без БД.
- `assignments` не вестигиально: серию рвёт резолюция (value vs target +
  confidence-гейт), а `assignments` нужен для (а) ретроспективного active-set —
  какие метрики репортить — (б) «anchor = первый флаг серии» и (в) `drill_id`
  выходной записи (самый свежий назначенный для M).

---

## Границы (что 2B НЕ делает)

- **Фронт не трогаем** — ноль изменений фронта. Но «не трогаем» ≠ «не сломается»:
  добавляем top-level `drill_progress` в `evidence_report` и `progress_explained`
  в `CoachReport`. CRA-фронт игнорит неизвестные ключи → ок, но это **verify-пункт**
  (ReportView рендерит известные ключи, новые не роняют сборку), а не предположение.
- **UI-панель динамики §G → 2C** (собрать HU-тренд + Voltaic-ранг разом).
- **Поле «дата съёмки» / DB-миграция → UI-спек.** `order_uncertain` пока `True`.
- **KovaaK's/Voltaic API, Steam ID, двухсигнальная тир-прогрессия,
  `settle_jitter` триггер трекинг-supplementary → 2C** (порог jitter не калиброван).
- **Тир статичен** — тир-бампа в 2B нет.
- **Каузальность — никогда** (guard Компонента 3).
- **Движок без БД** — история инжектится; `build_report` получает `drill_history=()`.
- **correction «решено» не вводим** — target-less прокси, единый anchor (YAGNI:
  понятие «решено» для correction = устойчивый чистый прогон ≥K клипов, не 2B).

## Edge-матрица (консолидировано, чтобы план не промахнулся)

| Случай | Поведение |
|---|---|
| Первый клип / истории нет | `drill_progress = []` (ретро-пустота; фронт рисует empty-state §G) |
| История есть, но для M флага в ней нет (новая слабость этого клипа) | НЕ в `drill_progress` (уедет свежим дриллом в `coach_report`); ретро-active-set игнорит; **никакого `baseline_set`** |
| Флаг → резолюция → не рефлагнута | выпадает (нет открытой серии) |
| Флаг, выпал из назначений (трим/невыбор), **неразрешён** | anchor держится (Баг A) |
| Разрешена-и-вернулась (target-ful) | новый anchor после резолюции |
| Correction (target-less) | единый anchor от первого флага, **не рвётся** |
| Correction `count==0` (`value_key=flicks_analysed`) | `directional_meaningful=False` → skip как insufficient, не мусор |
| Null current (`mae_hu` None) | `delta=None`, confidence `insufficient` |
| Эндпоинт `insufficient` (anchor/current) | `min` → insufficient; под-target-но-insufficient → **не** `resolved_now`, обычная дельта |
| Резолюционный клип `insufficient` | не точка резолюции (Компонент 2 гейт) |
| bias | `abs()`-нормировка через общий хелпер |
| Переанализ того же `clip_id` | дедуп, свежая побеждает |
| Порядок | `order_uncertain=True` всегда |

## Тест-стратегия (паттерн 2A — синтетика, без БД/API для числовой логики)

- **Движок `compute_drill_progress(findings, drill_history)`** — синтетические
  `ClipSnapshot`-списки покрывают КАЖДУЮ строку матрицы: кумулятив-не-clip-to-clip,
  отсутствие-дрилла-не-рвёт, резолюция-рвёт-и-реанкорит, резолюция-требует-≥hypothesis,
  correction-единый-anchor + вырожденец-skip, bias-abs, null-current, min-confidence
  (оба-diagnosis / один-hypothesis / один-insufficient), `resolved_now`, `series_len`,
  пустой-первый-клип, `order_uncertain=True` на выходе, correction-серия на
  вырожденном flicks_analysed-флаге остаётся skip.
  **Граничный тест округления/точности:** суб-HU дельта (0.2 HU) НЕ схлопывается в
  `flat` (докажет, что `_r`, а не integer-`round`); current ровно на `target` при
  разной сырой точности anchor/current даёт стабильный `resolved_now` (докажет
  единую нормировку — anchor и current в одном пространстве, граница не флипает).
- **Рефактор общего хелпера** — регрессия: существующий `test_drill_catalog` зелёный
  (поведение `build_criterion` не изменилось); тест «`compute_metric_criterion` и
  `build_criterion` согласны на одних values»; **греп-гард: ноль импортов
  `engine → coach`** (хелпер вернул dict, не `SuccessCriterion`).
- **Валидатор** — (а) дельта заземлена / выдуманная дельта отклонена;
  (б) **каузальный бан явно** — `сработал`/`благодаря дриллу` в `summary` → reject,
  в `caveats` → reject, в `progress_explained.explanation` → reject (замечание A
  формально закрыто); (в) `progress_explained.direction` ≠ engine → reject;
  (г) progress-`confidence` матчится против `drill_progress`, не `findings`
  (two-confidence trap); (д) hedged progress + утвердительное слово → reject.
- **Промпт** — лёгкий (правило `drill_progress` присутствует); озвучивание коуча
  проверяется схемой/валидатором, не живым API.
- **Пайплайн `history_provider` дефолт** — backend-тест (нужен sqlmodel, как
  `test_backend_api`): дедуп по `clip_id`, исключение текущего, порядок по
  `created_at`, `coach_failed`→`flagged=[]`. Env-гейт как у существующих backend-тестов;
  числовая логика движка от него не зависит.

## Принятые решения (2026-07-07)

1. **Объём 2B — компоненты B/C/F + кавеат порядка.** UI §G → 2C; дата съёмки → UI-спек.
2. **Точка отсчёта — кумулятивная (anchor = первый флаг неразрешённой серии).**
   Clip-to-clip неверен для «сдвинулась ли после совета» (baseline гонится за игроком,
   стабильный рост читается как flat).
3. **confidence дельты = `min(anchor, current)`** — дельта не надёжнее худшего конца.
4. **Разрыв серии — по резолюции метрики** (value vs target + confidence `≥ hypothesis`),
   НЕ по отсутствию дрилла. correction — единый anchor, не рвётся.
5. **Общий хелпер критерия в `engine/`, возвращает нейтральный dict** (анти-цикл;
   движок автономен). `build_criterion` — тонкая обёртка.
6. **guard структурный (Option 1):** `progress_explained` с enum-`direction`
   (матч `==`) и `confidence` против `drill_progress`; каузальный бан явно на
   `summary`+`caveats`+`progress.explanation`+`rationale`+`findings_explained`.
7. **Пайплайн — инжектируемый `history_provider`** (тупой добытчик; дедуп по
   `clip_id`; CLI → `[]`).
8. **Порядок `drill_progress` — канонический `CORE_METRICS`** (детерминизм; UX-сорт
   «regressed первыми» — UI-слой 2C).
9. **Фронт не трогаем, но verify-пункт:** новые ключи не роняют сборку.
10. **Единая нормировка + точность:** `normalize` применяет тот же per-`value_key`
    трансформ, что `baseline` (вкл. округление `_r`/`int`); `delta = _r(...)` до
    baseline-точности, НЕ до целого. anchor и current в одном пространстве →
    границы `flat`/резолюции точны (граничный тест обязателен).

## Следующий шаг

Spec self-review, затем `superpowers:writing-plans` — детальный TDD-имплемент-план
2B по компонентам 1→2→3→4 (хелпер → `drill_progress` → guard → пайплайн).
