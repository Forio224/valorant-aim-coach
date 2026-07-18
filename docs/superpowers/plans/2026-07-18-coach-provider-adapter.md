# Coach Provider Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Позволить коучу выбирать LLM-провайдера/модель (Anthropic и Google Gemini) через env/CLI, чтобы сравнивать качество советов на одном evidence-JSON; дефолт — бесплатный Gemini.

**Architecture:** Извлекаем общий код кадров/картинок в `coach/providers/common.py`, переносим текущий Anthropic-клиент в `coach/providers/anthropic.py`, добавляем `coach/providers/gemini.py` на официальном SDK `google-genai`, выбор — фабрика `coach/providers/factory.py` по `COACH_PROVIDER`. `coach/client.py` остаётся тонким реэкспортом ради обратной совместимости. Интерфейс провайдера минимален: `generate(evidence, frame_paths, feedback=None) -> CoachReport`.

**Tech Stack:** Python 3, pytest, Pydantic, `anthropic` SDK, `google-genai` SDK, Pillow (ресайз кадров).

## Global Constraints

- **Управляющий принцип:** числа считает только движок; VLM объясняет. Groundedness-валидация (`coach/validate.py`) — провайдер-независимая, НЕ трогать.
- **Интерфейс провайдера:** ровно `generate(evidence: dict, frame_paths: Sequence[Path], feedback: Optional[str] = None) -> CoachReport`. Это единственное, что вызывает `run_coach_validated`.
- **Обратная совместимость:** `from coach.client import CoachClient, DEFAULT_MODEL, MAX_IMAGES, COACH_IMAGE_MAX_WIDTH` обязаны продолжать работать — существующие тесты и импорты (`coach_cli.py`, `backend/services/analysis_pipeline.py`) их используют.
- **Дефолт провайдера:** `gemini` (при незаданном `COACH_PROVIDER`). Anthropic доступен через `COACH_PROVIDER=anthropic`.
- **Ключи только из env/.env:** `GEMINI_API_KEY` (Gemini), `ANTHROPIC_API_KEY` (Anthropic). Никаких ключей в коде/тестах кроме заглушечных `"test-key"`.
- **Ресайз кадров-улик:** до 1024px по ширине, JPEG quality 85 (как сейчас) — общий для всех провайдеров.
- **Кап картинок:** `MAX_IMAGES = 10` (env `COACH_MAX_IMAGES` в пайплайне уже режет раньше).
- **Тесты без сети:** SDK всегда подменяется заглушкой; реальный вызов Gemini проверяется только ручным smoke-тестом (Task 6, вне CI).
- **Запуск тестов:** `.\.venv\Scripts\python.exe -m pytest -q`.

---

### Task 1: Извлечь общий код кадров/картинок в `coach/providers/common.py`

Рефакторинг без смены поведения: общие помощники (нумерация кадров, base64-ресайз, константы) переезжают в новый модуль. Существующий `CoachClient` пока остаётся в `coach/client.py`, но начинает импортировать помощники из `common`. Все текущие тесты обязаны остаться зелёными.

**Files:**
- Create: `coach/providers/__init__.py`
- Create: `coach/providers/common.py`
- Create: `tests/test_coach_providers_common.py`
- Modify: `coach/client.py` (заменить локальные `_frame_number`/`_encode_frame`/константы на импорт из `common`, реэкспортировать имена)

**Interfaces:**
- Produces:
  - `coach.providers.common.frame_number(path: Path) -> Optional[int]`
  - `coach.providers.common.encode_frame(path: Path) -> str` (base64-JPEG, ресайз до `COACH_IMAGE_MAX_WIDTH`)
  - `coach.providers.common.capped_frames(frame_paths: Sequence[Path], max_images: int) -> List[Path]`
  - `coach.providers.common.frame_numbers(paths: Sequence[Path]) -> List[int]` (номера, пропуская `None`)
  - `coach.providers.common.frame_label(path: Path) -> str` (`"Кадр-улика 177"` или `"Кадр-улика frame_x.jpg"`)
  - Константы: `COACH_IMAGE_MAX_WIDTH = 1024`, `COACH_IMAGE_JPEG_QUALITY = 85`, `MAX_IMAGES = 10`

- [ ] **Step 1: Написать падающий тест на публичный API common**

Создать `tests/test_coach_providers_common.py`:

```python
# -*- coding: utf-8 -*-
"""Тесты общих помощников провайдеров: нумерация, ресайз, кап, подписи."""
import base64
import io
from pathlib import Path

from coach.providers import common

FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_frame_number_parses_padded_name():
    assert common.frame_number(Path("frame_000177.jpg")) == 177
    assert common.frame_number(Path("noNumberHere")) is None


def test_frame_numbers_skips_unnumbered():
    paths = [Path("frame_000010.jpg"), Path("banner.jpg"), Path("frame_000020.jpg")]
    assert common.frame_numbers(paths) == [10, 20]


def test_frame_label_uses_number_or_name():
    assert common.frame_label(Path("frame_000177.jpg")) == "Кадр-улика 177"
    assert common.frame_label(Path("weird.jpg")) == "Кадр-улика weird.jpg"


def test_capped_frames_limits_to_max():
    paths = [Path(f"frame_{n:06d}.jpg") for n in range(20)]
    assert len(common.capped_frames(paths, 10)) == 10
    assert common.capped_frames(paths, 10) == paths[:10]


def test_encode_frame_small_is_byte_identical(tmp_path):
    p = tmp_path / "frame_000001.jpg"
    p.write_bytes(FAKE_JPEG)
    assert base64.b64decode(common.encode_frame(p)) == FAKE_JPEG


def test_encode_frame_shrinks_wide(tmp_path):
    from PIL import Image

    p = tmp_path / "frame_000001.jpg"
    Image.new("RGB", (2000, 1120), (30, 40, 50)).save(p, format="JPEG")
    decoded = Image.open(io.BytesIO(base64.b64decode(common.encode_frame(p))))
    assert decoded.width == common.COACH_IMAGE_MAX_WIDTH
    assert decoded.height == 573  # round(1120 * 1024/2000)


def test_constants():
    assert common.COACH_IMAGE_MAX_WIDTH == 1024
    assert common.COACH_IMAGE_JPEG_QUALITY == 85
    assert common.MAX_IMAGES == 10
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_providers_common.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'coach.providers'`

- [ ] **Step 3: Создать пакет и `common.py`**

Создать `coach/providers/__init__.py` (пустой файл).

Создать `coach/providers/common.py`:

```python
# -*- coding: utf-8 -*-
"""Общий код провайдеров коуча: нумерация кадров, base64-ресайз, подписи.

Числа-биллинга картинок считаются по пикселям (≈ ш×в/750), поэтому кадры
ужимаются по ширине перед подачей. Полноразмерные JPEG на диске не трогаем —
они нужны фронту для лайтбокса; ужимается только копия в запрос.
"""
import base64
import io
import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

MAX_IMAGES = 10
COACH_IMAGE_MAX_WIDTH = 1024    # ниже ~800 аннотации-улики становятся нечитаемы
COACH_IMAGE_JPEG_QUALITY = 85

_FRAME_RE = re.compile(r"(\d+)")


def frame_number(path: Path) -> Optional[int]:
    """Номер кадра из имени файла вида frame_000177.jpg."""
    match = _FRAME_RE.search(path.stem)
    return int(match.group(1)) if match else None


def frame_numbers(paths: Sequence[Path]) -> List[int]:
    """Номера кадров по порядку, пропуская файлы без числа в имени."""
    return [n for n in (frame_number(p) for p in paths) if n is not None]


def frame_label(path: Path) -> str:
    """Подпись перед картинкой: 'Кадр-улика 177' или по имени файла."""
    number = frame_number(path)
    return f"Кадр-улика {number}" if number is not None else f"Кадр-улика {path.name}"


def capped_frames(frame_paths: Sequence[Path], max_images: int) -> List[Path]:
    """Первые max_images кадров — общий кап для всех провайдеров."""
    return list(frame_paths)[:max_images]


def encode_frame(path: Path) -> str:
    """Base64-JPEG кадра, ужатого до COACH_IMAGE_MAX_WIDTH по ширине.

    Уже маленькие кадры и всё, что PIL не смог декодировать (битый/не-JPEG
    файл), отдаём как есть — коучинг не должен падать из-за одного кадра."""
    raw = path.read_bytes()
    try:
        from PIL import Image  # ленивый импорт: без Pillow отдаём оригинал

        with Image.open(io.BytesIO(raw)) as img:
            if img.width <= COACH_IMAGE_MAX_WIDTH:
                return base64.b64encode(raw).decode("ascii")
            height = round(img.height * COACH_IMAGE_MAX_WIDTH / img.width)
            resized = img.convert("RGB").resize(
                (COACH_IMAGE_MAX_WIDTH, height), Image.LANCZOS
            )
            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=COACH_IMAGE_JPEG_QUALITY)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — битый/не-JPEG кадр не должен ронять коуча
        logger.warning("кадр %s не ужать (битый?), отдаю оригинал", path.name)
        return base64.b64encode(raw).decode("ascii")
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_providers_common.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Переключить `coach/client.py` на общие помощники**

В `coach/client.py`:
1. Удалить локальные `_FRAME_RE`, `_frame_number`, `_encode_frame` и константы `COACH_IMAGE_MAX_WIDTH`, `COACH_IMAGE_JPEG_QUALITY`, `MAX_IMAGES`.
2. Добавить импорт и реэкспорт-алиасы вверху (после `from coach.schema import CoachReport`):

```python
from coach.providers.common import (
    COACH_IMAGE_JPEG_QUALITY,
    COACH_IMAGE_MAX_WIDTH,
    MAX_IMAGES,
    capped_frames,
    encode_frame,
    frame_label,
    frame_number,
    frame_numbers,
)
```

3. В `build_content` заменить тело на использование общих помощников:

```python
    def build_content(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> List[dict]:
        """Контент user-сообщения: текст с JSON, затем подпись+картинка на улику.

        feedback — перечень ошибок groundedness при ретрае (Stage B2);
        добавляется финальным текстовым блоком."""
        paths = capped_frames(frame_paths, self.max_images)
        content: List[dict] = [
            {"type": "text", "text": build_user_text(report, frame_numbers(paths))}
        ]
        for path in paths:
            content.append({"type": "text", "text": frame_label(path) + ":"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": encode_frame(path),
                    },
                }
            )
        if feedback is not None:
            content.append({"type": "text", "text": feedback})
        return content
```

4. Удалить теперь неиспользуемые импорты `base64`, `io`, `re` из `coach/client.py`, если они больше нигде не нужны (оставить `os`, `logging`, `Path`, `typing`, `anthropic`).

- [ ] **Step 6: Запустить весь набор тестов коуча — обратная совместимость**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_client.py tests/test_coach_providers_common.py -q`
Expected: PASS (все прежние тесты `test_coach_client.py` + новые common зелёные)

- [ ] **Step 7: Commit**

```bash
git add coach/providers/__init__.py coach/providers/common.py coach/client.py tests/test_coach_providers_common.py
git commit -m "refactor(coach): вынести общий код кадров/картинок в providers/common"
```

---

### Task 2: Перенести Anthropic-клиент в `coach/providers/anthropic.py`, `coach/client.py` → реэкспорт

Физический перенос текущего `CoachClient` в пакет провайдеров. `coach/client.py` становится тонким шимом. Поведение и публичный API не меняются — существующий `tests/test_coach_client.py` остаётся зелёным без правок.

**Files:**
- Create: `coach/providers/anthropic.py` (тело текущего `coach/client.py` после Task 1)
- Modify: `coach/client.py` (сделать реэкспортом)

**Interfaces:**
- Consumes: `coach.providers.common` (Task 1)
- Produces:
  - `coach.providers.anthropic.CoachClient` с методом `generate(evidence, frame_paths, feedback=None) -> CoachReport`
  - `coach.providers.anthropic.DEFAULT_MODEL = "claude-sonnet-5"`, `MAX_IMAGES`, `DEFAULT_EFFORT`
  - `coach.client` реэкспортирует: `CoachClient, DEFAULT_MODEL, DEFAULT_EFFORT, MAX_IMAGES, COACH_IMAGE_MAX_WIDTH, COACH_IMAGE_JPEG_QUALITY`

- [ ] **Step 1: Переместить содержимое в `coach/providers/anthropic.py`**

Создать `coach/providers/anthropic.py` со ВСЕМ текущим содержимым `coach/client.py` (после правок Task 1). Импорт общих помощников поменять на относительный/пакетный:

```python
from coach.providers.common import (
    COACH_IMAGE_JPEG_QUALITY,
    COACH_IMAGE_MAX_WIDTH,
    MAX_IMAGES,
    capped_frames,
    encode_frame,
    frame_label,
    frame_numbers,
)
```

Обновить docstring модуля первой строкой:

```python
"""Anthropic-провайдер коуча: сборка мультимодального сообщения и structured output.

Модель: env COACH_MODEL, по умолчанию claude-sonnet-5. ...
"""
```

Остальное (класс `CoachClient`, `DEFAULT_MODEL`, `DEFAULT_EFFORT`, `MAX_TOKENS`, `SDK_MAX_RETRIES`, `build_content`, `generate`, `_log_usage`) — без изменений логики.

- [ ] **Step 2: Заменить `coach/client.py` на реэкспорт**

Полностью переписать `coach/client.py`:

```python
# -*- coding: utf-8 -*-
"""Обратная совместимость: CoachClient переехал в coach.providers.anthropic.

Исторический путь импорта. Новый код выбирает провайдера через
coach.providers.factory.create_coach_client().
"""
from coach.providers.anthropic import (  # noqa: F401
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    MAX_IMAGES,
    CoachClient,
)
from coach.providers.common import (  # noqa: F401
    COACH_IMAGE_JPEG_QUALITY,
    COACH_IMAGE_MAX_WIDTH,
)
```

- [ ] **Step 3: Запустить существующие тесты Anthropic-клиента — без правок**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_client.py -q`
Expected: PASS (все прежние тесты зелёные — импорты `from coach.client import ...` работают через шим)

- [ ] **Step 4: Прогнать весь набор — ничего не сломалось**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (полный набор зелёный)

- [ ] **Step 5: Commit**

```bash
git add coach/providers/anthropic.py coach/client.py
git commit -m "refactor(coach): перенести Anthropic-клиент в providers/anthropic, client.py -> реэкспорт"
```

---

### Task 3: Gemini-провайдер `coach/providers/gemini.py`

Новый клиент на официальном SDK `google-genai` (Interactions API). Structured output по Pydantic-схеме `CoachReport`, картинки — те же ужатые JPEG через `common`. Понятная ошибка при отсутствии ключа. SDK всегда подменяется заглушкой в тестах.

**Files:**
- Create: `coach/providers/gemini.py`
- Create: `tests/test_coach_gemini.py`
- Modify: `backend/requirements.txt` (добавить `google-genai`)
- Modify: `requirements.txt` (добавить `google-genai` — движок/CLI тоже могут дергать коуча офлайн)

**Interfaces:**
- Consumes: `coach.providers.common` (Task 1), `coach.prompt.SYSTEM_PROMPT`, `coach.prompt.build_user_text`, `coach.schema.CoachReport`
- Produces:
  - `coach.providers.gemini.GeminiCoachClient(api_key=None, model=None, max_images=MAX_IMAGES)`
  - метод `build_input(report, frame_paths, feedback=None) -> List[dict]`
  - метод `generate(report, frame_paths, feedback=None) -> CoachReport`
  - `coach.providers.gemini.DEFAULT_MODEL = "gemini-2.5-flash"`

> **Замечание по SDK (актуальность 2026-07):** текущий `google-genai` использует Interactions API: `client.interactions.create(model=..., input=[...], response_format={...})`, ответ читается как `interaction.output_text`. Точные имена kwargs/атрибутов подтверждаются smoke-тестом (Task 6). Клиент изолирует единственный вызов SDK, поэтому расхождение правится в одном месте. Системный промпт кладём первым текстовым блоком `input` (робастно вне зависимости от наличия отдельного system-параметра).

- [ ] **Step 1: Написать падающие тесты Gemini-клиента**

Создать `tests/test_coach_gemini.py`:

```python
# -*- coding: utf-8 -*-
"""Тесты GeminiCoachClient: сборка input, кап картинок, structured output, ключ."""
import base64
import json
from pathlib import Path

import pytest

from coach.providers.gemini import DEFAULT_MODEL, GeminiCoachClient
from coach.schema import CoachReport

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "friend_clip3.json"
FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


@pytest.fixture
def report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def frames_dir(tmp_path: Path) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    for n in [177, 244, 251, 276, 371, 394, 479, 487, 507, 179, 600, 601]:
        (d / f"frame_{n:06d}.jpg").write_bytes(FAKE_JPEG)
    return d


def _client() -> GeminiCoachClient:
    return GeminiCoachClient(api_key="test-key")


def test_default_model():
    assert DEFAULT_MODEL == "gemini-2.5-flash"
    assert _client().model == "gemini-2.5-flash"


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("COACH_MODEL", "gemini-3.5-flash")
    assert GeminiCoachClient(api_key="test-key").model == "gemini-3.5-flash"


def test_explicit_model_beats_env(monkeypatch):
    monkeypatch.setenv("COACH_MODEL", "gemini-3.5-flash")
    c = GeminiCoachClient(api_key="test-key", model="gemini-2.5-flash-lite")
    assert c.model == "gemini-2.5-flash-lite"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiCoachClient()


def test_build_input_starts_with_system_then_report(report, frames_dir):
    parts = _client().build_input(report, sorted(frames_dir.glob("*.jpg")))
    # первый блок — системный промпт, второй — текст с JSON
    assert parts[0]["type"] == "text"
    assert "тренер по аиму" in parts[0]["text"].lower() or "Valorant" in parts[0]["text"]
    assert parts[1]["type"] == "text"
    assert '"player_id": "friend"' in parts[1]["text"]


def test_build_input_caps_images(report, frames_dir):
    paths = sorted(frames_dir.glob("*.jpg"))
    assert len(paths) == 12
    parts = _client().build_input(report, paths)
    images = [p for p in parts if p["type"] == "image"]
    assert len(images) == 10


def test_image_parts_are_base64_jpeg_with_labels(report, frames_dir):
    paths = [frames_dir / "frame_000177.jpg"]
    parts = _client().build_input(report, paths)
    images = [p for p in parts if p["type"] == "image"]
    assert len(images) == 1
    assert images[0]["mime_type"] == "image/jpeg"
    assert base64.b64decode(images[0]["data"]) == FAKE_JPEG
    idx = parts.index(images[0])
    assert parts[idx - 1]["type"] == "text"
    assert "177" in parts[idx - 1]["text"]


def test_build_input_appends_feedback(report, frames_dir):
    parts = _client().build_input(
        report, sorted(frames_dir.glob("*.jpg")), feedback="кадр 999 не существует"
    )
    assert parts[-1]["type"] == "text"
    assert "кадр 999 не существует" in parts[-1]["text"]


def test_generate_parses_structured_output(report, frames_dir, monkeypatch):
    coach_report = CoachReport(summary="ок", findings_explained=[], drills=[], caveats=[])
    captured: dict = {}

    class StubInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class Resp:
                output_text = coach_report.model_dump_json()
                usage = None

            return Resp()

    class StubGenaiClient:
        interactions = StubInteractions()

    c = _client()
    monkeypatch.setattr(c, "_client", StubGenaiClient())
    result = c.generate(report, sorted(frames_dir.glob("*.jpg")))

    assert isinstance(result, CoachReport)
    assert result.summary == "ок"
    assert captured["model"] == "gemini-2.5-flash"
    assert isinstance(captured["input"], list)
    assert any(p["type"] == "image" for p in captured["input"])
    # structured output настроен на JSON
    assert captured["response_format"]["mime_type"] == "application/json"
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_gemini.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'coach.providers.gemini'`

- [ ] **Step 3: Реализовать `coach/providers/gemini.py`**

```python
# -*- coding: utf-8 -*-
"""Gemini-провайдер коуча: evidence-JSON + кадры-улики -> CoachReport.

SDK google-genai (Interactions API). Structured output — по Pydantic-схеме
CoachReport (response_format с JSON-схемой), поэтому контракт и groundedness-
валидация работают без адаптации. Системный промпт кладётся первым текстовым
блоком input. Ключ — GEMINI_API_KEY из окружения/.env.
"""
import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence

from coach.prompt import SYSTEM_PROMPT, build_user_text
from coach.providers.common import (
    MAX_IMAGES,
    capped_frames,
    encode_frame,
    frame_label,
    frame_numbers,
)
from coach.schema import CoachReport

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"   # vision + structured output + free tier


class GeminiCoachClient:
    """Обёртка google-genai: evidence-JSON + кадры-улики -> CoachReport."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_images: int = MAX_IMAGES,
    ):
        self.model = model or os.environ.get("COACH_MODEL", DEFAULT_MODEL)
        self.max_images = max_images
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY")
        if not key:
            raise ValueError(
                "GEMINI_API_KEY не задан — положи ключ в .env "
                "(создать: https://aistudio.google.com/apikey)"
            )
        from google import genai  # ленивый импорт: тесты подменяют _client

        self._client = genai.Client(api_key=key)

    def build_input(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> List[dict]:
        """Список блоков input: системный промпт, текст с JSON, затем на каждую
        улику подпись+картинка; feedback (ретрай) — финальным текстовым блоком."""
        paths = capped_frames(frame_paths, self.max_images)
        parts: List[dict] = [
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": build_user_text(report, frame_numbers(paths))},
        ]
        for path in paths:
            parts.append({"type": "text", "text": frame_label(path) + ":"})
            parts.append(
                {
                    "type": "image",
                    "data": encode_frame(path),
                    "mime_type": "image/jpeg",
                }
            )
        if feedback is not None:
            parts.append({"type": "text", "text": feedback})
        return parts

    def generate(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> CoachReport:
        """Один вызов Gemini: structured JSON -> Pydantic CoachReport."""
        response = self._client.interactions.create(
            model=self.model,
            input=self.build_input(report, frame_paths, feedback),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": CoachReport.model_json_schema(),
            },
        )
        self._log_usage(response)
        return CoachReport.model_validate_json(response.output_text)

    @staticmethod
    def _log_usage(response) -> None:
        """Фактический расход токенов в лог — видимость для сравнения моделей."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        logger.info(
            "coach usage (gemini): input=%s output=%s total=%s",
            getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", "?")),
            getattr(usage, "output_tokens", getattr(usage, "completion_tokens", "?")),
            getattr(usage, "total_tokens", "?"),
        )
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_gemini.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Добавить зависимость `google-genai` в оба requirements**

В `backend/requirements.txt` добавить строкой после `anthropic`:

```
google-genai
```

В `requirements.txt` добавить последней строкой:

```
google-genai
```

- [ ] **Step 6: Установить зависимость и повторить тесты**

Run: `.\.venv\Scripts\python.exe -m pip install google-genai`
Then: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_gemini.py -q`
Expected: PASS (реальный импорт `from google import genai` в конструкторе резолвится; тесты по-прежнему зелёные, так как `_client` подменяется, но конструктор с `api_key="test-key"` создаёт настоящий `genai.Client` без сети)

- [ ] **Step 7: Commit**

```bash
git add coach/providers/gemini.py tests/test_coach_gemini.py backend/requirements.txt requirements.txt
git commit -m "feat(coach): Gemini-провайдер (google-genai) со structured output"
```

---

### Task 4: Фабрика провайдеров `coach/providers/factory.py`

Единая точка выбора клиента по `COACH_PROVIDER` (+ `COACH_MODEL`). Дефолт — `gemini`. Неизвестный провайдер — понятная ошибка.

**Files:**
- Create: `coach/providers/base.py` (Protocol-контракт для типизации)
- Create: `coach/providers/factory.py`
- Create: `tests/test_coach_factory.py`

**Interfaces:**
- Consumes: `coach.providers.anthropic.CoachClient` (Task 2), `coach.providers.gemini.GeminiCoachClient` (Task 3)
- Produces:
  - `coach.providers.base.CoachProvider` (typing.Protocol с `generate(evidence, frame_paths, feedback=None) -> CoachReport`)
  - `coach.providers.factory.DEFAULT_PROVIDER = "gemini"`
  - `coach.providers.factory.create_coach_client(provider: Optional[str] = None, model: Optional[str] = None) -> CoachProvider`

- [ ] **Step 1: Написать падающие тесты фабрики**

Создать `tests/test_coach_factory.py`:

```python
# -*- coding: utf-8 -*-
"""Тесты фабрики провайдеров: выбор по env/аргументу, дефолт, ошибки."""
import pytest

from coach.providers.anthropic import CoachClient
from coach.providers.factory import DEFAULT_PROVIDER, create_coach_client
from coach.providers.gemini import GeminiCoachClient


@pytest.fixture(autouse=True)
def _dummy_keys(monkeypatch):
    # заглушечные ключи, чтобы конструкторы SDK не падали (сеть не трогается)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.delenv("COACH_PROVIDER", raising=False)
    monkeypatch.delenv("COACH_MODEL", raising=False)


def test_default_provider_is_gemini():
    assert DEFAULT_PROVIDER == "gemini"
    assert isinstance(create_coach_client(), GeminiCoachClient)


def test_env_selects_anthropic(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "anthropic")
    assert isinstance(create_coach_client(), CoachClient)


def test_env_selects_gemini(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "gemini")
    assert isinstance(create_coach_client(), GeminiCoachClient)


def test_explicit_arg_beats_env(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "gemini")
    assert isinstance(create_coach_client(provider="anthropic"), CoachClient)


def test_provider_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("COACH_PROVIDER", "Anthropic")
    assert isinstance(create_coach_client(), CoachClient)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="openai"):
        create_coach_client(provider="openai")


def test_model_passed_through():
    c = create_coach_client(provider="gemini", model="gemini-3.5-flash")
    assert c.model == "gemini-3.5-flash"
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_factory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'coach.providers.factory'`

- [ ] **Step 3: Создать `base.py` и `factory.py`**

Создать `coach/providers/base.py`:

```python
# -*- coding: utf-8 -*-
"""Контракт провайдера коуча — минимальный интерфейс для run_coach_validated."""
from pathlib import Path
from typing import Optional, Protocol, Sequence

from coach.schema import CoachReport


class CoachProvider(Protocol):
    """Единственное, что вызывает пайплайн: generate(...) -> CoachReport."""

    def generate(
        self,
        report: dict,
        frame_paths: Sequence[Path],
        feedback: Optional[str] = None,
    ) -> CoachReport: ...
```

Создать `coach/providers/factory.py`:

```python
# -*- coding: utf-8 -*-
"""Выбор провайдера коуча по COACH_PROVIDER (+ COACH_MODEL). Дефолт — gemini.

Сравнение моделей: COACH_PROVIDER/COACH_MODEL в .env для пайплайна, флаги
--provider/--model у coach_cli.py для офлайн-прогона на готовом evidence-JSON.
"""
import os
from typing import Optional

from coach.providers.anthropic import CoachClient
from coach.providers.base import CoachProvider
from coach.providers.gemini import GeminiCoachClient

DEFAULT_PROVIDER = "gemini"

_PROVIDERS = {
    "gemini": GeminiCoachClient,
    "anthropic": CoachClient,
}


def create_coach_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> CoachProvider:
    """Клиент выбранного провайдера. Неизвестный провайдер -> ValueError."""
    name = (provider or os.environ.get("COACH_PROVIDER") or DEFAULT_PROVIDER).lower()
    client_cls = _PROVIDERS.get(name)
    if client_cls is None:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ValueError(
            f"неизвестный COACH_PROVIDER '{name}'; поддерживаются: {supported}"
        )
    return client_cls(model=model)
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_factory.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add coach/providers/base.py coach/providers/factory.py tests/test_coach_factory.py
git commit -m "feat(coach): фабрика провайдеров create_coach_client (дефолт gemini)"
```

---

### Task 5: Подключить фабрику в пайплайн и CLI, обновить `.env.example`

Пайплайн и офлайн-CLI перестают жёстко создавать `CoachClient()` — идут через фабрику. `coach_cli.py` получает флаг `--provider`. Документация окружения пополняется.

**Files:**
- Modify: `backend/services/analysis_pipeline.py:133-135` (fallback-создание клиента)
- Modify: `coach_cli.py` (флаг `--provider`, создание через фабрику)
- Modify: `.env.example` (GEMINI_API_KEY, COACH_PROVIDER)
- Create: `tests/test_coach_provider_wiring.py`

**Interfaces:**
- Consumes: `coach.providers.factory.create_coach_client` (Task 4)

- [ ] **Step 1: Написать падающие тесты подключения**

Создать `tests/test_coach_provider_wiring.py`:

```python
# -*- coding: utf-8 -*-
"""Пайплайн и CLI создают клиента через фабрику провайдеров."""
import coach_cli
from backend.services import analysis_pipeline


def test_pipeline_fallback_uses_factory(monkeypatch):
    calls = {}

    def fake_factory(*args, **kwargs):
        calls["made"] = True

        class FakeResult:
            coach_report = None
            errors = ["stub"]
            attempts = 1
            coach_failed = True

        return object()

    monkeypatch.setattr(
        "coach.providers.factory.create_coach_client", fake_factory)
    # run_coach_validated импортируется ЛОКАЛЬНО внутри _run_coach из
    # coach.validate — патчим по месту определения, не по имени в пайплайне.
    monkeypatch.setattr(
        "coach.validate.run_coach_validated",
        lambda *a, **k: type("R", (), {
            "coach_report": None, "errors": [], "attempts": 1,
            "coach_failed": True})())

    # coach_client=None -> должен пойти в фабрику
    analysis_pipeline._run_coach(
        None, {"findings": []}, [], analysis_pipeline.PipelineConfig())
    assert calls.get("made") is True


def test_coach_cli_accepts_provider_flag(monkeypatch, tmp_path):
    captured = {}

    def fake_factory(provider=None, model=None):
        captured["provider"] = provider
        captured["model"] = model

        class FakeClient:
            def generate(self, *a, **k):
                from coach.schema import CoachReport
                return CoachReport(
                    summary="ок", findings_explained=[], drills=[], caveats=[])

        return FakeClient()

    monkeypatch.setattr(
        "coach.providers.factory.create_coach_client", fake_factory)

    report = tmp_path / "r.json"
    report.write_text('{"findings": []}', encoding="utf-8")
    out = tmp_path / "out.json"

    coach_cli.main(
        ["--provider", "gemini", "--model", "gemini-3.5-flash",
         str(report), "--out", str(out)])
    assert captured["provider"] == "gemini"
    assert captured["model"] == "gemini-3.5-flash"
```

> Примечание: точная сигнатура `_run_coach` — `_run_coach(coach_client, report, frame_paths, config)`. `PipelineConfig()` создаётся с дефолтами; если конструктор требует аргументов, посмотреть определение в `analysis_pipeline.py` и передать минимально необходимые.

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_provider_wiring.py -q`
Expected: FAIL — `coach_cli.main` не знает `--provider` (argparse: unrecognized arguments) и/или пайплайн зовёт `CoachClient()` вместо фабрики

- [ ] **Step 3: Пайплайн — создавать клиента через фабрику**

В `backend/services/analysis_pipeline.py`, в `_run_coach`, заменить блок:

```python
        client = coach_client
        if client is None:
            from coach.client import CoachClient
            client = CoachClient()
```

на:

```python
        client = coach_client
        if client is None:
            from coach.providers.factory import create_coach_client
            client = create_coach_client()
```

- [ ] **Step 4: `coach_cli.py` — флаг `--provider` и фабрика**

В `coach_cli.py`:

1. Добавить аргумент после `--model`:

```python
    parser.add_argument(
        "--provider", default=None,
        help="провайдер LLM: gemini | anthropic (по умолчанию из COACH_PROVIDER)")
```

2. Заменить создание клиента:

```python
    if client is None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        from coach.providers.factory import create_coach_client

        client = create_coach_client(provider=args.provider, model=args.model)
```

Обновить docstring модуля: упомянуть `--provider` и что ключ берётся под провайдера (`GEMINI_API_KEY`/`ANTHROPIC_API_KEY`).

- [ ] **Step 5: Запустить тесты подключения — убедиться, что проходят**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_provider_wiring.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Обновить `.env.example`**

Заменить блок `# --- Обязательное ---` и секцию `# --- Коуч ---`.

В начало добавить провайдера и ключ Gemini (после строки `ANTHROPIC_API_KEY=sk-ant-...`):

```
# Ключ Google Gemini для VLM-коуча (провайдер по умолчанию). Создать:
# https://aistudio.google.com/apikey . Держать ТОЛЬКО в .env.
GEMINI_API_KEY=AIza...
```

В секцию `# --- Коуч ---` первой строкой добавить:

```
# Провайдер LLM коуча: gemini (по умолчанию) | anthropic.
# COACH_PROVIDER=gemini
# Модель коуча. Для gemini: gemini-2.5-flash (дефолт), gemini-2.5-flash-lite,
# gemini-3.5-flash. Для anthropic: claude-sonnet-5 (дефолт), claude-haiku-4-5.
# COACH_MODEL=gemini-2.5-flash
```

Удалить/переписать старую строку `# Модель Claude для коуча (по умолчанию claude-sonnet-5).` и `# COACH_MODEL=claude-sonnet-5`, чтобы не было двух `COACH_MODEL`.

- [ ] **Step 7: Прогнать весь набор тестов**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (полный набор зелёный, включая новые тесты провайдеров)

- [ ] **Step 8: Commit**

```bash
git add backend/services/analysis_pipeline.py coach_cli.py .env.example tests/test_coach_provider_wiring.py
git commit -m "feat(coach): пайплайн и CLI через фабрику провайдеров, .env.example для Gemini"
```

---

### Task 6: Ручной smoke-тест Gemini на реальном ключе (вне CI)

Проверка, что реальный вызов `google-genai` соответствует коду (имена kwargs/атрибутов Interactions API, id модели, чтение usage). Правки — точечные, в одном `generate`/`_log_usage`, если SDK отличается от предположений.

**Files:**
- Возможные точечные правки: `coach/providers/gemini.py` (только вызов SDK)

- [ ] **Step 1: Убедиться, что ключ на месте**

Проверить, что в `.env` есть `GEMINI_API_KEY=...` (пользователь пересоздал ключ в AI Studio после того, как старый засветился в переписке).

- [ ] **Step 2: Прогнать коуча офлайн на готовом evidence-JSON**

Взять готовый отчёт и кадры из `reports/`. Пример:

Run:
```
.\.venv\Scripts\python.exe coach_cli.py reports/friend_clip3.json --frames reports/evidence/friend_clip3 --provider gemini --out coach_gemini_smoke.json
```
Expected: `CoachReport записан: coach_gemini_smoke.json (попыток: 1)` (или 2 при одном ретрае groundedness). Если получен HTTP/атрибутная ошибка SDK — сверить с актуальной докой google-genai и поправить вызов в `generate`/`_log_usage`, затем повторить.

- [ ] **Step 3: Глазами проверить осмысленность отчёта**

Открыть `coach_gemini_smoke.json`: `summary` на русском, `findings_explained` ссылаются на реальные метрики, числа не выдуманы (иначе groundedness дал бы `coach_failed`). Сравнить с эталонным Anthropic-прогоном при желании:
```
.\.venv\Scripts\python.exe coach_cli.py reports/friend_clip3.json --frames reports/evidence/friend_clip3 --provider anthropic --out coach_anthropic_smoke.json
```
(требует баланса Anthropic; при отсутствии — пропустить сравнение).

- [ ] **Step 4: Если правил вызов SDK — прогнать тесты и закоммитить**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_coach_gemini.py -q`
Expected: PASS

```bash
git add coach/providers/gemini.py
git commit -m "fix(coach): выровнять вызов Gemini SDK по факту smoke-теста"
```

Если правок не потребовалось — коммита нет; smoke-файлы `coach_*_smoke.json` не коммитить (добавить в `.gitignore` при необходимости).

---

## Замечания по актуальности API (для исполнителя)

- **Interactions API `google-genai`** (2026-07): `client.interactions.create(model=..., input=[...], response_format={...})`, ответ — `interaction.output_text`. Это новее моего опыта; точные имена подтверждаются Task 6. Весь риск изолирован в `GeminiCoachClient.generate`/`_log_usage`.
- **Модель по умолчанию** `gemini-2.5-flash` выбрана как надёжный free-tier с vision + structured output; легко меняется через `COACH_MODEL`. Актуальные модели/лимиты: https://ai.google.dev/gemini-api/docs/models
- **Системный промпт** подаётся первым текстовым блоком `input` — робастно вне зависимости от наличия отдельного system-параметра. Если SDK явно поддерживает system/instructions-параметр, можно перенести туда (мелкое улучшение, не блокер).
