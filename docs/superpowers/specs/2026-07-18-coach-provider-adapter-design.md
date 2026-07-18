# Дизайн: мульти-провайдерный адаптер VLM-коуча (Anthropic + Gemini)

Дата: 2026-07-18
Статус: утверждён пользователем (brainstorming), готов к плану реализации

## Задача

Коуч (Phase B) прибит гвоздями к Anthropic SDK (`coach/client.py`). Нужна
возможность выбирать провайдера/модель LLM — в первую очередь бесплатный
Google Gemini (vision + structured output на free tier) — и сравнивать
качество советов разных моделей на одном и том же evidence-JSON.

Мотивация: баланс Anthropic закончился (возвращён на карту); Gemini Flash
даёт бесплатный тариф с vision и structured output; интересно сравнить
качество рекомендаций разных моделей.

## Решения, принятые на брейншторме

| Вопрос | Решение |
|---|---|
| Провайдеры на старте | Anthropic + Gemini (интерфейс расширяемый) |
| Переключение | env `COACH_PROVIDER`/`COACH_MODEL` для пайплайна + флаги `--provider`/`--model` в `coach_cli.py` для офлайн-сравнения |
| Дефолт при незаданном `COACH_PROVIDER` | **gemini** (Anthropic остаётся через `COACH_PROVIDER=anthropic`) |
| Подход | Нативные SDK + тонкий Protocol-интерфейс (не OpenAI-compat слой, не LiteLLM) |

## Архитектура

Новый пакет `coach/providers/`:

```
coach/providers/
├── base.py       # Protocol CoachProvider: generate(report, frame_paths, feedback) -> CoachReport
├── common.py     # общее: _encode_frame (ресайз JPEG), _frame_number, сборка подписей кадров
├── anthropic.py  # текущий CoachClient переезжает сюда, логика не меняется
├── gemini.py     # GeminiCoachClient на официальном SDK google-genai
└── factory.py    # create_coach_client(): COACH_PROVIDER -> экземпляр клиента
```

- `coach/client.py` остаётся реэкспортом `CoachClient` — существующие
  импорты (`backend/services/analysis_pipeline.py`, тесты) не ломаются.
- Интерфейс минимальный: `run_coach_validated` зависит только от
  `client.generate(report, frame_paths, feedback=None) -> CoachReport`.

### Gemini-клиент

- SDK `google-genai` (официальный). Structured output нативно по Pydantic:
  `response_schema=CoachReport` — контракт и groundedness-валидация работают
  без адаптации.
- Кадры-улики: тот же ресайз до 1024px по ширине (общий код `common.py`),
  подача как inline-байты `image/jpeg` с текстовыми подписями
  «Кадр-улика N:» перед каждым (паритет с Anthropic-путём).
- Ключ: `GEMINI_API_KEY` из `.env` (у Google SDK `GOOGLE_API_KEY` имеет
  приоритет, документируем `GEMINI_API_KEY` как основной). Ключ отсутствует —
  понятная ошибка при создании клиента в фабрике, не в глубине пайплайна.
- Usage-лог из `usage_metadata` (prompt/candidates tokens) в том же
  формате логгера, что у Anthropic-клиента.
- Модель по умолчанию: Flash-класс; точный ID зафиксировать при реализации
  по актуальной таблице моделей/rate-limits (кандидаты: gemini-3-flash,
  gemini-2.5-flash). Критерии: vision + structured output + free tier.

### Фабрика и конфигурация

- `create_coach_client(provider=None, model=None)`:
  `provider or env COACH_PROVIDER or "gemini"`; модель —
  `model or env COACH_MODEL or дефолт провайдера`.
- Неизвестный провайдер — `ValueError` с перечнем поддерживаемых.
- `analysis_pipeline` создаёт клиента через фабрику (инжекция для тестов
  сохраняется).
- `coach_cli.py`: новый флаг `--provider`, существующий `--model`.
- `.env.example`: добавить `GEMINI_API_KEY`, `COACH_PROVIDER`,
  обновить комментарий `COACH_MODEL`.

## Что НЕ меняется

- Groundedness-валидация (`coach/validate.py`), ретрай, деградация
  `coach_failed`, `finalize_plan`, Pydantic-схема `CoachReport`, фронт.
- Управляющий принцип: числа считает только движок; анти-выдумка ловит
  галлюцинации любой модели.

## Безопасность

- Ключи только в `.env` (в `.gitignore`), никогда в коде/чате.
- Засвеченный в переписке ключ Gemini пользователь пересоздаёт в AI Studio.

## Тестирование (TDD, без сети)

1. Фабрика: выбор провайдера по env; явный аргумент важнее env; неизвестный
   провайдер → `ValueError`; отсутствие `GEMINI_API_KEY` → понятная ошибка.
2. Gemini-клиент с мок-SDK: собирает контент (текст + подписи + байты
   кадров), уважает кап `max_images`, добавляет feedback-блок при ретрае,
   парсит structured output в `CoachReport`, логирует usage.
3. Обратная совместимость: `from coach.client import CoachClient` работает;
   существующие тесты коуча зелёные.
4. Ручной smoke: `coach_cli.py --provider gemini` на готовом evidence-JSON
   из `reports/` с реальным ключом (вне CI).
