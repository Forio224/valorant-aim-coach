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
