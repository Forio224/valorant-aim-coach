# Роадмап Phase B: VLM-коуч поверх движка (переход A+ → B, полный продукт)

## Context

Phase A+ завершена (Stage 0–6, 2026-06-10): движок `engine/` выдаёт versioned
evidence-JSON (schema 1.0) — эпизоды, findings (placement / consistency / bias /
correction) с уликами-кадрами и уровнем уверенности (diagnosis / hypothesis /
insufficient), плюс продольный per-player профиль (`profiles/{player_id}.json`).
YOLO-детектор heads_v3 (conf=0.4) воспроизводит GT-паспорт на невиданном клипе —
путь видео→цифры работает без разметки.

Phase B соединяет это в продукт: evidence-JSON + кадры-улики → Claude → человеческий
коучинг-отчёт (диагноз + тренировочный план), встроенный в backend-пайплайн
(upload → YOLO → движок → коуч → БД) и показанный игроку в браузере с
аннотированными кадрами-доказательствами. Легаси-путь «сырые кадры → Claude с общим
промптом» (`backend/services/vlm_client.py`) и шаблонный
`backend/recommendation_engine.py` уходят в ретайр — именно их Phase A строилась
заменить.

**Решения, принятые с пользователем (2026-06-10):**
1. Рамки — полный продукт: от клипа до совета в браузере.
2. Вход VLM — evidence-JSON (источник истины для чисел) + кадры-улики как картинки
   (контекст ситуации; числа из картинок брать запрещено).
3. Контент отчёта — диагноз по уликам + приоритизированный тренировочный план
   (дриллы Kovaak's/Range/in-game), привязанный к конкретным findings.
4. UI — кадры-улики показываются игроку с наложенной разметкой (центр-прицел,
   бокс головы, стрелка оффсета).
5. Порядок — «изнутри наружу»: ядро коуча как CLI (офлайн-итерации на готовых
   отчётах friend/author, дифф-тест как в Phase A) → backend → frontend.

**Управляющие принципы (наследуются из Phase A):** числа только из движка — VLM не
измеряет, а объясняет; уважать confidence (hypothesis ≠ diagnosis в формулировках);
per-player всегда, людей не сливать; язык отчёта — русский.

---

## Стадии

### Stage B0 — Schema 1.1 + кадры-улики (`engine/evidence_frames.py`)

**Goal:** материализовать улики из JSON в аннотированные JPEG — общий ресурс для
VLM (вход) и frontend (показ игроку).

**Build:**
- Расширить evidence-записи в `engine/report.py` числовой геометрией:
  `dx_hu`, `dy_hu`, `head_height_px` на кадре улики (для оконных улик — кадр-якорь).
  `schema_version` → `1.1`. Пиксельные координаты головы восстановимы:
  прицел = фиксированный центр (W/2, H/2), `head_px = центр + d*_hu × head_height_px`
  — пересэмплинг видео не нужен.
- Новый `engine/evidence_frames.py`: по видео + отчёту вырезать кадры улик
  (cv2 seek по номеру кадра), наложить разметку: маркер центра-прицела, бокс головы
  (центр + высота из геометрии), стрелка оффсета, подпись (время, dx/dy HU, суть
  улики). Сохранять `reports/evidence/{player}_{clip}/frame_{NNNNNN}.jpg`;
  дедупликация кадров между findings; кап на количество (по умолчанию 10).
- CLI: `aim_metrics.py --evidence-frames DIR` (работает в обоих режимах gt/yolo).

**Reuse:** `FrameSample` (`aim_metrics.py:84`) уже несёт `dx_hu/dy_hu/head_height_px`;
`build_report` (`engine/report.py:192`); паттерн открытия видео из `_crosshair_for_video`.

**Done-when:** на clip3 кадр 177 сгенерирован и разметка глазами совпадает с уликой
(враг слева-выше, прицел ниже линии — улика уже верифицирована в Stage 6);
юнит-тесты на восстановление пиксельной геометрии из HU.

### Stage B1 — Ядро коуча: контракт + промпт + клиент (`coach/`)

**Goal:** evidence-JSON + кадры → структурированный коучинг-отчёт. CLI-инструмент,
отлаживаемый офлайн без backend.

**Build:**
- `coach/schema.py` — Pydantic-контракт `CoachReport`:
  - `summary` — портрет игрока человеческим языком (2–3 абзаца);
  - `findings_explained[]` — `{metric, explanation, evidence_frames[], confidence}` —
    объяснение каждого finding со ссылками на кадры;
  - `drills[]` — `{priority, name, platform: kovaaks|range|ingame, dose,
    target_metric, success_criterion}` — каждый дрилл привязан к конкретному finding;
  - `caveats[]` — ограничения (мало данных, прокси-метрика коррекции и т.п.).
- `coach/prompt.py` — системный промпт: роль коуча; ЖЁСТКИЕ правила groundedness
  (каждое число — из JSON; кадры — только контекст ситуации: позиция, угол,
  способности; запрещено изобретать метрики/кадры/события); confidence-язык
  (hypothesis → «предварительно, нужно больше клипов»); русский язык; structured
  output через tool use.
- `coach/client.py` — Anthropic SDK: модель по умолчанию `claude-sonnet-4-6`
  (конфиг через env `COACH_MODEL`; при имплементации свериться со skill
  `claude-api` по актуальным ID/ценам), ретраи на 429 (паттерн уже есть в
  `vlm_client.py`), кап картинок ≤10, сборка сообщения JSON+images.
- `coach_cli.py` (корень проекта) — `python coach_cli.py reports/friend_clip3.json
  --frames reports/evidence/... --out coach_friend_clip3.json`.

**Reuse:** retry-паттерн из `backend/services/vlm_client.py`; готовые отчёты
`reports/friend_clip3.json` и профили `profiles/` как офлайн-фикстуры.

**Done-when:** дифф-тест — на отчётах friend (X-bias +0.20, Y-перелёты,
КАЛИБРОВКА) и author (X-bias −0.46 влево, чище коррекция) коуч выдаёт РАЗНЫЕ
портреты и разные дриллы; каждое число/кадр в тексте трассируется к JSON вручную.

### Stage B2 — Groundedness-валидация (анти-выдумка)

**Goal:** механическая проверка, что коуч не выдумал, — продолжение принципа
«не коучить на неизмеренном».

**Build:**
- `coach/validate.py`: каждый `evidence_frame` из ответа существует в отчёте;
  каждое HU-число в тексте встречается в `values` (с допуском округления);
  каждый дрилл ссылается на существующий metric; hypothesis-findings не
  сформулированы как диагноз (стоп-слова).
- Провал → один повторный запрос с перечнем ошибок; повторный провал →
  деградация: игроку отдаётся отчёт движка без коуч-текста + флаг
  `coach_failed` (ошибку не глотать, логировать).
- Golden-фикстуры записанных ответов; юнит-тесты валидатора на синтетике
  (подсаженный фиктивный кадр, выдуманное число, диагноз-из-гипотезы).

**Done-when:** валидатор ловит все три класса подсаженных ошибок; на реальных
ответах B1 проходит чисто.

### Stage B3 — Backend-пайплайн (ретайр легаси-пути)

**Goal:** продуктовый путь upload → YOLO → движок → коуч → БД, замена
«кадры→Claude».

**Build:**
- `backend/services/analysis_pipeline.py`: видео → ultralytics-инференс
  (heads_v3 `best.pt`, путь в конфиге, conf=0.4 — калибровка закрыта, не трогать)
  → `context_for_video` (player_id + опц. sens/eDPI/agent/map из формы) →
  эпизоды → метрики → `build_report` → evidence-кадры (B0) → коуч (B1+B2) →
  результат.
- Upload-эндпоинт: обязательный `player_id`, опциональные метаданные (честный
  возврат input-space, который видео не видит).
- БД: хранить evidence-JSON и CoachReport (JSON-колонки в `AnalysisSession`);
  статусы PENDING → DETECTING → MEASURING → COACHING → COMPLETED/FAILED;
  при `coach_failed` — COMPLETED с частичным результатом (движок есть, текста нет).
- Профили: после каждого клипа `profile_store` обновляет `profiles/{player_id}.json`
  (идемпотентно по clip_id) — продольное накопление работает в продукте.
- Раздача кадров-улик: FastAPI StaticFiles на каталог evidence-кадров.
- **Ретайр:** `backend/services/vlm_client.py` (прямые кадры),
  `backend/recommendation_engine.py`, `backend/video_processor.py`,
  `backend/metrics_calculator.py` — удалить; CLAUDE.md обновить.

**Reuse:** фон-таски и polling-каркас `backend/main.py`; SQLModel-плумбинг
`backend/database.py`; весь `engine/` как библиотека (он уже импортируем).

**Done-when:** POST clip3.mp4 (player_id=friend) → GET возвращает coach-отчёт;
числа движка в ответе API совпадают с CLI-прогоном `--source yolo` на том же клипе.

### Stage B4 — Frontend: отчёт с уликами

**Goal:** игрок видит диагноз с доказательствами, а не абстрактный текст.

**Build:**
- Форма загрузки: player_id + опциональные sens/eDPI/agent/map.
- Страница отчёта: summary-портрет → findings с confidence-бейджами
  (диагноз/гипотеза) и аннотированными кадрами-уликами рядом с каждым объяснением
  → таблица дрилл-плана (приоритет, платформа, дозировка, критерий успеха) →
  caveats. Прогресс по статусам пайплайна вместо немого ожидания.
- Существующие компоненты (`UploadVideo`, `AnalyticsDisplay`,
  `TrainingRecommendations`) переработать под новый контракт.

**Done-when:** отчёт clip3 читается в браузере: кадры-улики видны, дриллы
привязаны к findings, гипотезы визуально отличимы от диагнозов.

### Stage B5 — Продакшн-гигиена + E2E-закалка

**Goal:** довести до «можно дать другу».

**Build:**
- Конфиг: `.env.example` обновить (COACH_MODEL, YOLO_WEIGHTS, лимиты);
  CORS сузить с `*`; кап стоимости (max_tokens, кап картинок — уже в B1).
- Сквозной прогон обоих игроков: author/output_clip и friend/clip2+clip3 —
  профили накапливаются, отчёты различаются (продуктовый дифф-тест).
- Ошибочные пути: видео без голов (пустой клип сериализуется — уже покрыто),
  отказ API Claude, битый файл.
- README/CLAUDE.md: новая архитектура, легаси-секции убрать.

**Done-when:** оба игрока прогнаны через браузер end-to-end; все pytest зелёные.

---

## Порядок исполнения

B0 → B1 → B2 (ядро, офлайн) → B3 (backend) → B4 (frontend) → B5 (закалка).
B0–B2 не трогают backend вообще — итерации промпта дёшевы и быстры.

## Verification (end-to-end)

1. **B0:** открыть сгенерированный кадр 177 clip3 — разметка совпадает с уликой.
2. **B1:** дифф-тест friend vs author — разные портреты/дриллы; ручная трассировка
   каждого числа к JSON.
3. **B2:** подсаженные ошибки (фиктивный кадр / число / диагноз-из-гипотезы)
   ловятся валидатором.
4. **B3:** числа API == числа CLI `--source yolo` на том же клипе.
5. **B4:** визуальная проверка отчёта в браузере (скриншот).
6. Все стадии: pytest (82 существующих + новые) зелёные.

## Что осознанно НЕ делаем (YAGNI / мёртвые ветки)

- Видео-вход напрямую в VLM (вернуло бы выдумывание, которое Phase A устраняла).
- Reaction-в-мс, калькулятор сенсы, профиль мыши — input-space, видео не видит
  (зафиксированный принцип Phase A).
- Чат с коучем / follow-up диалог — после того, как одноразовый отчёт заработает.
- Аккаунты/авторизация/billing — продукт пока локальный.
- Расширение `recommendation_engine.py` — ретайр, не рефакторинг.

## Ключевые файлы

| Файл | Действие |
|---|---|
| `engine/report.py` | schema 1.1: + dx_hu/dy_hu/head_height_px в evidence |
| `engine/evidence_frames.py` | новый: вырезка + аннотация кадров-улик |
| `coach/schema.py`, `coach/prompt.py`, `coach/client.py`, `coach/validate.py` | новые: ядро коуча |
| `coach_cli.py` | новый: офлайн-CLI коуча |
| `backend/services/analysis_pipeline.py` | новый: YOLO→движок→коуч |
| `backend/main.py`, `backend/database.py` | правка: эндпоинты, статусы, JSON-колонки |
| `frontend/src/**` | переработка под новый контракт |
| `backend/services/vlm_client.py`, `backend/recommendation_engine.py`, `backend/video_processor.py`, `backend/metrics_calculator.py` | ретайр (удалить) |
