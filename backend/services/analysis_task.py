# -*- coding: utf-8 -*-
"""Исполнение разбора как переиспользуемая задача (Этап 1 запуска).

Одна и та же логика — статусы, персист результата, FAILED при исключении —
нужна двум путям: BackgroundTasks (dev) и arq-воркеру (прод). Пайплайн
инжектируется, как детектор и коуч внутри него: тесты и воркер живут без
YOLO/Redis/сети.
"""
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisJob:
    """Всё, что нужно воркеру для разбора; сериализуется в очередь как dict."""
    session_id: str
    video_path: str
    player_id: str
    clip_id: str
    sens: Optional[float] = None
    edpi: Optional[float] = None
    agent: Optional[str] = None
    map_name: Optional[str] = None
    training_platform: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "session_id": self.session_id,
            "video_path": self.video_path,
            "player_id": self.player_id,
            "clip_id": self.clip_id,
            "sens": self.sens,
            "edpi": self.edpi,
            "agent": self.agent,
            "map_name": self.map_name,
            "training_platform": self.training_platform,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "AnalysisJob":
        return cls(**payload)


def run_analysis_session(db, job: AnalysisJob, *, evidence_dir: str,
                         pipeline: Callable,
                         history_provider=None) -> None:
    """Синхронно исполнить разбор и записать исход сессии в БД.

    evidence_dir — корень улик; кадры сессии кладутся в подкаталог
    {session_id} и наружу отдаются как URL /evidence/{session_id}/...
    """
    sid = uuid.UUID(job.session_id)

    def on_status(status: str) -> None:
        db.update_session(sid, status=status)

    try:
        session_evidence_dir = str(Path(evidence_dir) / job.session_id)
        result = pipeline(
            job.video_path, job.player_id, clip_id=job.clip_id,
            sens=job.sens, edpi=job.edpi, agent=job.agent,
            map_name=job.map_name, training_platform=job.training_platform,
            evidence_dir=session_evidence_dir, on_status=on_status,
            history_provider=history_provider)

        frame_urls = [f"/evidence/{job.session_id}/{Path(p).name}"
                      for p in result.evidence_frames]
        db.update_session(
            sid,
            status="COMPLETED",
            evidence_report=json.dumps(result.evidence_report,
                                       ensure_ascii=False),
            coach_report=(json.dumps(result.coach_report, ensure_ascii=False)
                          if result.coach_report is not None else None),
            coach_failed=result.coach_failed,
            coach_errors=json.dumps(result.coach_errors, ensure_ascii=False),
            evidence_frames=json.dumps(frame_urls),
        )
    except Exception as exc:                       # noqa: BLE001 — в БД и лог
        logger.exception("пайплайн упал: session %s", job.session_id)
        db.update_session(sid, status="FAILED", error=str(exc))
