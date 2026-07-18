# -*- coding: utf-8 -*-
"""Тупой добытчик истории для петли прогресса (Фаза 2B).

Пайплайн — только сбор данных; КАЖДОЕ число считает движок. Читает прошлые
сессии игрока, дедуплицирует по clip_id (свежая побеждает — зеркалит
идемпотентность profile_store), исключает текущий клип, сортирует по времени
и раскладывает в ClipSnapshot-и для engine.compute_drill_progress.
"""
import json
from typing import Callable, List, Optional, Sequence

from engine.version import METRICS_VERSION


def build_clip_snapshots(sessions: Sequence[dict],
                         exclude_clip_id: str) -> List[dict]:
    """Сессии (уже распарсенные dict-и) → ClipSnapshot-и. Без БД (тестируемо).

    Контракт METRICS_VERSION (Фаза 3): в anchor-серии идут только клипы текущей
    методики. Отчёт без поля = версия 1 (до атрибуции цели / гейта пре-айма);
    сравнивать его числа с текущими нельзя — иначе смена методики отрапортуется
    как прогресс игрока.
    """
    by_clip: dict = {}
    for s in sessions:
        ev = s.get("evidence_report")
        if s["clip_id"] == exclude_clip_id or ev is None:
            continue
        if ev.get("metrics_version", 1) != METRICS_VERSION:
            continue                       # клип по прежней методике — не сравниваем
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
