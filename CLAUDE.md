# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Valorant AI Aim Coach** — full-stack app: игрок загружает клип геймплея,
YOLO-детектор находит головы врагов, движок Phase A считает объективные
аим-метрики в Head Units, VLM-коуч (Claude) объясняет их человеческим языком
и выдаёт тренировочный план с кадрами-уликами.

**Управляющий принцип:** числа считает ТОЛЬКО движок — VLM не измеряет, а
объясняет (groundedness-валидация ловит выдумки). Per-player всегда: людей
в один портрет не сливаем.

## Running the Project

### Environment

Всегда запускать через `.\.venv\Scripts\python.exe` (системный Python без
torch; каталог `venv\` — сломанный, правильный — `.venv\`).

Copy `.env.example` to `.env`:
- `ANTHROPIC_API_KEY` — required для VLM-коуча
- `DATABASE_URL`, `UPLOAD_DIR`, `EVIDENCE_DIR`, `YOLO_WEIGHTS`, `PROFILE_DIR`,
  `COACH_MODEL`, `COACH_MAX_IMAGES` — опциональные ручки (см. .env.example)

### Backend

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm start   # http://localhost:3000
```

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Architecture

### Product pipeline (Stage B3)

```
POST /api/v1/analysis/upload   (file + player_id, опц. sens/edpi/agent/map_name)
  → сохранить видео в UPLOAD_DIR; clip_id = stem исходного имени файла
  → AnalysisSession (PENDING) в SQLite
  → фоновая задача backend/services/analysis_pipeline.run_pipeline():
      DETECTING  YOLO heads_v3 (conf=0.4 — колено холдаута, не трогать)
      MEASURING  сэмплы паспорта → segment_episodes → findings →
                 profile_store (продольный профиль, идемпотентно по clip_id) →
                 build_report (evidence-JSON schema 1.1) →
                 render_evidence_frames (аннотированные JPEG улики)
      COACHING   coach/client.py + coach/validate.py (1 ретрай →
                 деградация coach_failed: COMPLETED с частичным результатом)
  → COMPLETED | FAILED
GET /api/v1/analysis/{session_id}
  → status + evidence_report + coach_report + coach_failed + evidence_frames
    (URL вида /evidence/{session_id}/frame_NNNNNN.jpg — StaticFiles)
```

**Key files:**
- `backend/main.py` — FastAPI: upload/poll, статусы, StaticFiles /evidence
- `backend/database.py` — SQLModel `AnalysisSession` с JSON-колонками;
  URL нормализуется под psycopg3, даты — aware-UTC (`UTCDateTime`);
  dev/тесты — create_all на SQLite, прод — Postgres через
  `python -m alembic upgrade head` (миграции в `migrations/`)
- `backend/services/analysis_pipeline.py` — YOLO → движок → коуч;
  детектор и коуч-клиент инжектируются (тесты без torch/API)
- `backend/services/analysis_task.py` — исполнение разбора как задача
  (статусы/персист/FAILED), общая для обоих бэкендов очереди
- `backend/services/job_queue.py` — очередь: `QUEUE_BACKEND=background`
  (в процессе API, дефолт dev) | `arq` (Redis, переживает рестарт;
  `_job_id=session_id` — дедуп)
- `backend/worker.py` — arq-воркер:
  `python -m arq backend.worker.WorkerSettings` (нужен REDIS_URL);
  WORKER_MAX_JOBS=1 — GPU обрабатывает один клип за раз
- `backend/services/storage.py` — файлы: `STORAGE_BACKEND=local` (диск,
  дефолт) | `r2` (S3/R2: presigned PUT мимо API → POST /start; улики в
  бакете, отдаются presigned GET при поллинге; ретеншн клипов —
  lifecycle бакета на uploads/, 7 дней)

### Engine (Phase A, `engine/` + `aim_metrics.py`)

Прицел = фиксированный центр экрана; все метрики в Head Units.
- `aim_metrics.py` — паспорт (MAE/bias/std) + CLI (gt/yolo источники)
- `engine/clip_context.py` — идентичность клипа, fps из mp4
- `engine/episodes.py` — эпизоды (track birth→disappearance); gt-путь по CVAT
  id, yolo-путь через `segment_episodes` (greedy NN + gate)
- `engine/metrics/` — placement (пре-айм), consistency (диагноз
  калибровка/повторяемость), correction (перелёт/недолёт на фликах)
- `engine/profile_store.py` — продольный `profiles/{player_id}.json`
- `engine/report.py` — evidence-JSON schema 1.1 (числа + кадры-улики +
  confidence diagnosis/hypothesis/insufficient)
- `engine/evidence_frames.py` — аннотированные JPEG улики

### Coach (Phase B, `coach/`)

- `coach/schema.py` — Pydantic `CoachReport` (summary, findings_explained,
  drills, caveats)
- `coach/prompt.py` — groundedness-правила: числа только из JSON
- `coach/providers/` — мульти-провайдерный адаптер: `factory.create_coach_client`
  по `COACH_PROVIDER` (default **gemini**); `gemini.py` (google-genai
  Interactions API, default gemini-3.5-flash, ключ `GEMINI_API_KEY`),
  `anthropic.py` (default claude-sonnet-5, ключ `ANTHROPIC_API_KEY`),
  `common.py` (ресайз кадров, кап картинок); `coach/client.py` — реэкспорт
  для обратной совместимости
- `coach/validate.py` — механическая анти-выдумка: кадры/HU-числа/
  metric-ссылки/confidence-язык; `run_coach_validated` = 1 ретрай → coach_failed
- `coach_cli.py` — офлайн-прогон коуча на готовом evidence-JSON;
  `--provider gemini|anthropic` + `--model` для сравнения моделей

### CLI движка (офлайн-анализ)

```powershell
.\.venv\Scripts\python.exe aim_metrics.py --source gt --xml dataset1/clip2.xml --video dataset1/clip2.mp4 --player-id friend --episodes --placement --correction --save-profile --report-json reports/friend_clip2.json --evidence-frames reports/evidence/friend_clip2
.\.venv\Scripts\python.exe aim_metrics.py --source yolo --video dataset1/clip3.mp4 --player-id friend
```

### CV-Based Head Detection (standalone module)

`backend/centroid_head_detector.py` — OpenCV-альтернатива YOLO по цвету
подсветки врага (HSV): работает без сети, используется для отладки. Запуск:
`python backend/centroid_head_detector.py <video.mp4> [color_preset]`.

### Frontend (Stage B4)

React 18 (CRA), русский UI «Аим-паспорт». Сессия живёт в URL
(`?session=<id>` — отчёт можно открыть по ссылке).
- `src/api.js` — клиент API (`REACT_APP_API_BASE`, default :8000)
- `src/App.js` — фазы: форма → прогресс по статусам → отчёт
- `src/components/UploadForm.js` — файл + обязательный player_id +
  опциональные sens/eDPI/агент/карта
- `src/components/PipelineProgress.js` — станции DETECTING/MEASURING/COACHING
- `src/components/OffsetGlyph.js` — SVG-прицел с реальным смещением dx/dy
- `src/components/report/` — ReportView (сборка + фолбэк coach_failed на
  данных движка), FindingCard (бейджи уверенности: диагноз — сплошной,
  гипотеза — пунктир), EvidenceThumb + Lightbox (клик по улике — полный
  экран, Esc — закрыть), DrillTable, labels.js (словари + `humanLead` —
  главный тезис находки человеческим языком, детерминированно из чисел
  движка; сырые HU-числа спрятаны в свёрнутый блок «Числа движка»)

Дизайн-токены в `src/index.css`: цвет семантический (красный=«мимо»,
янтарный=гипотеза, зелёный=«в цель»), шрифты Unbounded + JetBrains Mono.
Скриншоты эталона: `reports/screenshots/b4_*.png`.

## Key Constraints

- **conf=0.4** для YOLO зафиксирован калибровкой на холдауте — не менять.
- **Клипы одного игрока** агрегируются в профиль; людей не смешивать
  (`--player-id` обязателен везде).
- **CORS** ограничен `ALLOWED_ORIGINS` (default `http://localhost:3000`);
  лимит загрузки `MAX_UPLOAD_MB` (default 300, синхронизирован с фронтом
  через `REACT_APP_MAX_UPLOAD_MB`).
- **Пустой клип** (нет голов): коуч НЕ вызывается (вызов VLM не тратится),
  сессия COMPLETED с `coach_failed` и понятной ошибкой; фронт показывает
  экран «Врагов в клипе не нашлось».
- **HU-нормировка**: `head_height_px` защищён `max(..., MIN_HEAD_PX)`.
- **Датасет**: в dataset1/ clip2+clip3 = друга, output_clip = автора.
