# Valorant AI Aim Coach

Загрузи клип геймплея — получи объективный разбор аима и тренировочный план
с кадрами-доказательствами.

## Как это работает

1. **YOLO** (heads_v3) находит головы врагов на каждом кадре.
2. **Движок** (Phase A) считает метрики в Head Units: MAE прицела, вертикальный/
   горизонтальный биас, стабильность, пре-айм при появлении врага,
   перелёты/недолёты на фликах — и копит продольный профиль игрока.
3. **VLM-коуч** (Claude) объясняет числа движка и назначает дриллы
   (Kovaak's / Range / in-game). Механический валидатор не даёт коучу
   выдумывать числа и кадры.

## Setup

1. `python -m venv .venv` и `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r backend/requirements.txt`
2. Скопировать `.env.example` в `.env`, вписать `ANTHROPIC_API_KEY`.
3. Backend: `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000`
4. Frontend: `cd frontend && npm install && npm start`

## Тесты

```
.\.venv\Scripts\python.exe -m pytest -q
```
