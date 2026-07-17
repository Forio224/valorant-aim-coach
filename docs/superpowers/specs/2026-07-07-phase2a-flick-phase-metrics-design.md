# Дизайн Фазы 2A: фаз-метрики флика

**Статус:** УТВЕРЖДАЕТСЯ (2026-07-07). Самодостаточная под-фаза: обогащает движок,
не зависит ни от петли прогресса (2B), ни от внешнего API (2C).
**Дата:** 2026-07-07. **Область:** только `engine/` (сегментация фаз + метрики,
встройка в `report.py`). Каталог, валидатор, промпт, выбор дрилла — НЕ трогаем.
**Родитель:** [2026-07-05-phase2-progress-loop-design.md](2026-07-05-phase2-progress-loop-design.md) — «Компонент A».

## Проблема

Движок меряет только *итог* наведения (`correction` = булево «перелетел/недолетел
по оси»), но не *процесс*: как быстро игрок добил цель после броска и была ли
доводка плавной. Это самый сильный непокрытый сигнал внутри клипа — скорость
закрытия дуэли эмпирически коррелирует с результатом сильнее, чем in-game accuracy.

## Цель

Разложить каждый флик на две фазы по ряду `offset(t)` и посчитать четыре новых
числа движком, **обогатив существующий `correction`-finding**. Никаких новых
findings, метрик каталога, дриллов или изменений в выборе дрилла VLM — только
богаче портрет. Управляющий принцип сохранён: числа считает движок, VLM их не
производит.

## Модель: две фазы одного `offset(t)`

`offset(t)` = `episode.samples[*].radial_hu` (расстояние голова↔фикс-прицел в Head
Units; 1 HU = высота головы). Данные уже есть — **новый детектор не нужен**.
Анализируем ТОТ ЖЕ набор флик-эпизодов, что и `correction`: `ep.kind == "flick"`
И `ep.peak_closing_speed_hu_s >= MIN_FLICK_SPEED_HU_S` (камера доминирует).

Окно анализа фаз — полный трек эпизода `[start_frame … end_frame]` (НЕ обрезанное
окно `correction._analysis_window`: стабилизацию надо ловить и за пределами
settle-маржи).

1. **Баллистика** — от старта до первого кадра `b`, где `radial_hu ≤ near_band_hu`
   (open-loop бросок; здесь живёт перелёт).
2. **Settle (доводка)** — от `b` до кадра `s` — момента стабилизации
   (**Вариант A**, см. ниже; closed-loop микрокоррекция).

## Определение конца settle-фазы (Вариант A — по стабилизации)

`s` = первый кадр ≥ `b`, где `radial_hu ≤ settle_tol_hu` **и** держится ниже
допуска непрерывно ≥ `SETTLE_STABLE_FRAMES` (K) кадров; `s` = первый кадр этого
устойчивого прогона.

Классификация флика по фазам:
- **arrived** — вошёл в near-band (нашёлся `b`);
- **settled** — нашёлся устойчивый прогон (нашёлся `s`).

Флик участвует в агрегатах **только если arrived И settled** (иначе чисел не
выдумываем — понижаем confidence через счётчики). Отдельно считаем `flicks_arrived`
и `flicks_settled`, чтобы честность была видна.

## Четыре метрики (все считает движок)

Пофликово, только для usable-фликов (arrived+settled). Определения уточнены после
ревью: overshoot = ИСТИННЫЙ перелёт через центр (не радиальный отскок), jitter — по
производной (рывковость, не разброс), добавлена метрика пути доводки.

### `flick_overshoot_hu` — истинный перелёт ЗА цель
Радиальный `offset` всегда ≥ 0, поэтому «отскок после минимума» ложно срабатывает
на дрожи у цели (точное попадание с микродрожью читалось бы как перелёт). Меряем
настоящий перелёт по ЗНАКОВЫМ осям `dx_hu`/`dy_hu` (та же логика, что в
`correction`): на оси фиксируем начальный знак (первый выход за `DEADBAND_HU`);
если позже знак меняется за deadband — перелёт был, его величина = макс.
`|смещение|` на противоположной стороне после пересечения (в окне `[start … s]`).
`flick_overshoot_hu` = максимум по осям (`0`, если ни одна ось не пересекла центр).
Согласован с булевыми `correction.x/y` (та же ось — теперь ещё и «на сколько HU»).

### `settle_time_frames` (+ `settle_time_ms`) — скорость доводки
`settle_time_frames = s − b`; сразу храним и `settle_time_ms = 1000·(s−b)/ctx.fps`
в результатах (не только для UI — упрощает отчёты и корреляции). Главный новый
диагностик, ортогональный placement/consistency/correction: «как быстро хороший
флик превращается в готовый выстрел».

### `settle_jitter_hu` — рывковость доводки (по производной)
`stdev(radial_hu)` меряет разброс: плавный спад `0.8→0.4` и дёрганый
`0.5→0.2→0.6→0.1` дают похожую дисперсию. Рывковость честнее меряется по первой
производной: `settle_jitter_hu = stdev(Δradial_hu)`, где
`Δradial_i = radial_hu[i] − radial_hu[i−1]` на `[b … s]`. Гладкая доводка =
согласованные шаги (низкий), «поймал-потерял» = скачущие (высокий). Триггер
трекинг-дрилла по нему — в 2C.

### `correction_path_hu` — эффективность доводки
`correction_path_hu = Σ |Δradial_hu|` на `[b … s]` — суммарный путь прицела на
доводке. При равном `settle_time` игрок, прошедший 5 HU, контролирует мышь лучше
прошедшего 20 HU. Почти ортогональна остальным трём (время / перелёт / рывковость
/ путь). Ортогональна `settle_jitter` тоже: та — изменчивость шага, эта —
суммарная магнитуда.

> Отклонены в 2A (YAGNI / избыточность): `first_pass_error_hu`, `correction_count`,
> `settle_efficiency` (производное от path), `peak_speed_hu_frame`,
> `deceleration_frames`. Первые три перекрываются с принятыми; последние две
> относятся к баллистике, а не к качеству доводки. Кандидаты на будущие фазы.

## Агрегация и confidence

- Агрегат по клипу — **медиана** по usable-фликам (устойчивее среднего на 3–8
  фликах): `flick_overshoot_hu_median`, `settle_time_frames_median`,
  `settle_jitter_hu_median`, `correction_path_hu_median`. `settle_time_ms_median`
  выводится из `settle_time_frames_median` и `ctx.fps`.
- `phase_confidence` по числу usable-фликов:
  - `insufficient` — usable == 0 (медианы = null, чисел нет);
  - `hypothesis` — 0 < usable < `MIN_FLICKS_FOR_PHASE`;
  - `diagnosis` — usable ≥ `MIN_FLICKS_FOR_PHASE`.
- `phase_confidence` **отдельный** от `correction.confidence` (у них разные
  основания: correction — по числу флик-эпизодов, фазы — по числу usable).

## Ручки (дефолты; калибруются на прогонах 2A)

| Ручка | Дефолт | Смысл |
|---|---|---|
| `NEAR_BAND_HU` | 0.8 | граница баллистика↔settle (вход в band) |
| `SETTLE_TOL_HU` | 0.35 | тесный допуск «на цели» |
| `SETTLE_STABLE_FRAMES` (K) | 3 | сколько кадров держать допуск = «успокоился» |
| `MIN_FLICKS_FOR_PHASE` | 3 | порог confidence фаз |

Наследуется из `correction`: гейт флика (`MIN_FLICK_SPEED_HU_S`), deadband-логика
знаков (для перелёта по осям — уже в `correction`). `NEAR_BAND_HU`/`SETTLE_TOL_HU`
финализируются после прогонов 2A на реальных клипах (родитель это закладывал).

## Архитектура и встройка

**Новый модуль `engine/metrics/flick_phase.py`** (отдельная ответственность:
`correction.py` = output-space вердикты по осям; `flick_phase.py` = разложение по
фазам). Потребляет `Sequence[Episode]` + `ClipContext`, использует тот же
предикат гейта флика.

- `@dataclass(frozen=True) FlickPhase`: пофликовая запись
  (`episode_index, start_frame, arrived, settled, flick_overshoot_hu,
  settle_time_frames, settle_jitter_hu, correction_path_hu,
  overshoot_evidence_frame`).
- `@dataclass(frozen=True) FlickPhaseReport`: `flicks_analysed, flicks_arrived,
  flicks_settled, *_median, phase_confidence, phases: Tuple[FlickPhase, ...]`.
- `compute_flick_phases(episodes, ctx, **knobs) -> FlickPhaseReport`.
- `format_flick_phases(report, ctx) -> str` (для CLI-вывода, как у `correction`).

**`engine/report.py`:** добавить агрегаты в `values` correction-finding'а и
пофликовый блок в evidence, **не трогая старые ключи** (`flicks_analysed`,
`x_overshoots` и т.д. — от них зависит `build_criterion("correction", …)` Фазы 1).
Улика фазы (`overshoot_evidence_frame`) = кадр пикового перелёта.

Пример `values` после 2A:
```json
{
  "flicks_analysed": 8, "x_overshoots": 5, "x_undershoots": 1,
  "y_overshoots": 0, "y_undershoots": 1,
  "flick_overshoot_hu_median": 0.9,
  "settle_time_frames_median": 11, "settle_time_ms_median": 183,
  "settle_jitter_hu_median": 0.12,
  "correction_path_hu_median": 1.6,
  "flicks_arrived": 8, "flicks_settled": 6,
  "phase_confidence": "diagnosis"
}
```

## Тесты (синтетические эпизоды, TDD)

- **чистый флик** — быстрый заход, оседает за K кадров, overshoot = 0, путь мал;
- **долгий settle** — вход в band, устойчивость только через много кадров →
  большой `settle_time_frames`/`settle_time_ms`;
- **истинный перелёт** — ось `dx_hu` пересекает центр (смена знака за deadband) →
  `flick_overshoot_hu` > 0 = макс. заход на противоположную сторону, улика на пике;
- **дрожь без перелёта** — микроколебания у цели БЕЗ смены знака → overshoot = 0
  (регрессия на старую радиальную формулу, которая дала бы ложный перелёт);
- **джиттер по производной** — плавный спад vs дёрганый с близким `stdev(radial)`,
  но разным `stdev(Δradial)` → `settle_jitter_hu` разводит их;
- **путь доводки** — два флика с равным `settle_time`, но разным Σ|Δradial| →
  `correction_path_hu` разный;
- **не дошёл** — offset никогда не входит в near-band → arrived=False, исключён;
- **не оселся** — вошёл в band, но не стабилизировался → settled=False,
  `settle_time_frames=null`, исключён из медиан;
- **confidence** — 0 usable → insufficient; <3 → hypothesis; ≥3 → diagnosis;
- **медиана/счётчики** — на смеси фликов.

Плюс: старые тесты `correction` и `test_report` не ломаются; старые ключи `values`
на месте (`build_criterion("correction")` работает без изменений).

## Кавеаты

- **Output-space прокси** (наследуется от `correction`): видим прицел↔голову, не
  ввод мыши; смена offset может быть стрейфом врага. Гейт по скорости + анализ
  только фликов это смягчают, но не устраняют.
- **Граница фаз — эвристика.** `near_band`/`settle_tol` — приближение; конец
  settle определён по стабилизации траектории, а не по реальному выстрелу
  (выстрела в данных нет).
- **Мало фликов** → `phase_confidence` честно понижается, числа не выдумываются.

## Границы (что 2A НЕ делает)

- **Не заводит новый finding/метрику каталога/дрилл.** settle — пока только число
  в `correction.values`, не отдельный диагностик с дриллом (это возможное
  расширение, но вне 2A).
- **Не назначает дрилл по settle_time и не триггерит трекинг-supplementary по
  jitter** — это Фаза 2C.
- **Не меняет `build_criterion("correction")`** — критерий correction остаётся
  directional, как в Фазе 1.
- **Не трогает петлю прогресса** (`drill_progress`, история) — это Фаза 2B.

## Следующий шаг

Spec self-review → ревью пользователем → `superpowers:writing-plans` для
детального имплемент-плана 2A.
