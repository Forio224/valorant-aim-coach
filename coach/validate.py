# -*- coding: utf-8 -*-
"""Groundedness-валидация коуч-отчёта (Stage B2).

Механическая анти-выдумка: ответ VLM сверяется с evidence-JSON движка по
четырём осям — кадры, HU-числа, metric-ссылки, confidence-язык. Числа в
дриллах не проверяются: целевые пороги — рекомендации, а не измерения.
Провал -> один ретрай с перечнем ошибок; повторный провал -> деградация
coach_failed (ошибка логируется, не глотается).
"""
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from coach.schema import CoachReport

logger = logging.getLogger(__name__)

RETRY_LIMIT = 2  # первый вызов + один повтор

_HU_NUMBER_RE = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s*HU\b")

# утвердительные слова, запрещённые в объяснениях гипотез (границы слов:
# «недостаточно» не должно срабатывать как «точно»)
_ASSERTIVE_STOPWORDS_RE = re.compile(
    r"\b(однозначно|доказано|гарантированно|безусловно|несомненно|очевидно|точно)\b",
    re.IGNORECASE,
)

_EVIDENCE_FRAME_KEYS = ("frame", "frame_start", "frame_end")
_EPISODE_FRAME_KEYS = ("start_frame", "end_frame", "multi_from_frame")
_EVIDENCE_HU_KEYS = ("dx_hu", "dy_hu", "head_height_px")
_HEDGED_CONFIDENCES = ("hypothesis", "insufficient")


@dataclass(frozen=True)
class CoachRunResult:
    """Итог прогона коуча с валидацией: отчёт или деградация coach_failed."""

    coach_report: Optional[CoachReport]
    errors: List[str]
    attempts: int
    coach_failed: bool


def _hu_numbers_in_text(text: str) -> List[float]:
    """HU-числа, упомянутые в строке (ноты/statement тоже источник истины)."""
    return [
        float(m.group(1).replace(",", "."))
        for m in _HU_NUMBER_RE.finditer(text)
    ]


def _known_frames(evidence: dict) -> set:
    """Все номера кадров, явно присутствующие в evidence-JSON."""
    frames = set()
    for episode in evidence.get("episodes", []):
        for key in _EPISODE_FRAME_KEYS:
            value = episode.get(key)
            if isinstance(value, int):
                frames.add(value)
    for finding in evidence.get("findings", []):
        for entry in finding.get("evidence", []):
            for key in _EVIDENCE_FRAME_KEYS:
                value = entry.get(key)
                if isinstance(value, int):
                    frames.add(value)
    return frames


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _known_numbers(evidence: dict) -> List[float]:
    """Пул чисел движка: values, геометрия улик/эпизодов, профиль, HU из нот."""
    pool: List[float] = []
    for finding in evidence.get("findings", []):
        pool.extend(
            float(v) for v in finding.get("values", {}).values() if _is_number(v)
        )
        pool.extend(_hu_numbers_in_text(finding.get("statement") or ""))
        pool.extend(_hu_numbers_in_text(finding.get("caveat") or ""))
        for entry in finding.get("evidence", []):
            pool.extend(
                float(entry[k]) for k in _EVIDENCE_HU_KEYS if _is_number(entry.get(k))
            )
            pool.extend(_hu_numbers_in_text(entry.get("note") or ""))
    for episode in evidence.get("episodes", []):
        pool.extend(
            float(v) for v in episode.get("birth", {}).values() if _is_number(v)
        )
        if _is_number(episode.get("peak_closing_speed_hu_s")):
            pool.append(float(episode["peak_closing_speed_hu_s"]))
    profile = evidence.get("profile") or {}
    pool.extend(float(v) for v in profile.values() if _is_number(v))
    return pool


def _check_hu_numbers(text: str, pool: List[float], where: str) -> List[str]:
    """Каждое HU-число текста должно совпасть с числом движка (по модулю,
    с допуском на округление до написанного числа знаков)."""
    errors = []
    for match in _HU_NUMBER_RE.finditer(text):
        raw = match.group(1)
        value = float(raw.replace(",", "."))
        digits = raw.replace(",", ".")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        tolerance = 0.5 * 10 ** -decimals + 1e-9
        if not any(abs(abs(value) - abs(known)) <= tolerance for known in pool):
            errors.append(
                f"число {raw} HU ({where}) не найдено в evidence-JSON"
            )
    return errors


def validate_coach_report(coach: CoachReport, evidence: dict) -> List[str]:
    """Список ошибок groundedness; пустой список = отчёт чист."""
    errors: List[str] = []
    frames_known = _known_frames(evidence)
    numbers_known = _known_numbers(evidence)
    findings_by_metric = {
        f["metric"]: f for f in evidence.get("findings", [])
    }

    for fe in coach.findings_explained:
        where = f"finding '{fe.metric}'"
        source = findings_by_metric.get(fe.metric)
        if source is None:
            errors.append(f"{where} отсутствует в отчёте движка")
        elif fe.confidence != source["confidence"]:
            errors.append(
                f"{where}: коуч заявил confidence '{fe.confidence}', "
                f"у движка '{source['confidence']}'"
            )
        for frame in fe.evidence_frames:
            if frame not in frames_known:
                errors.append(
                    f"кадр {frame} ({where}) не существует в evidence-JSON"
                )
        errors.extend(_check_hu_numbers(fe.explanation, numbers_known, where))
        if fe.confidence in _HEDGED_CONFIDENCES:
            stopword = _ASSERTIVE_STOPWORDS_RE.search(fe.explanation)
            if stopword:
                errors.append(
                    f"утвердительное слово '{stopword.group(1)}' в гипотезе "
                    f"({where}) — гипотеза не должна звучать как диагноз"
                )

    errors.extend(_check_hu_numbers(coach.summary, numbers_known, "summary"))

    for drill in coach.drills:
        if drill.target_metric not in findings_by_metric:
            errors.append(
                f"дрилл '{drill.name}' ссылается на несуществующий "
                f"metric '{drill.target_metric}'"
            )
    return errors


def _build_feedback(errors: List[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "Твой предыдущий ответ не прошёл механическую проверку "
        "groundedness. Исправь ошибки и верни отчёт заново, используя "
        "ТОЛЬКО кадры и числа из evidence-JSON:\n" + lines
    )


def run_coach_validated(
    client, evidence: dict, frame_paths: Sequence
) -> CoachRunResult:
    """Вызов коуча с валидацией: провал -> 1 ретрай -> деградация coach_failed."""
    feedback: Optional[str] = None
    errors: List[str] = []
    for attempt in range(1, RETRY_LIMIT + 1):
        if feedback is None:
            candidate = client.generate(evidence, frame_paths)
        else:
            candidate = client.generate(evidence, frame_paths, feedback=feedback)
        errors = validate_coach_report(candidate, evidence)
        if not errors:
            return CoachRunResult(
                coach_report=candidate,
                errors=[],
                attempts=attempt,
                coach_failed=False,
            )
        feedback = _build_feedback(errors)
    logger.error(
        "коуч не прошёл groundedness-валидацию после %d попыток: %s",
        RETRY_LIMIT,
        "; ".join(errors),
    )
    return CoachRunResult(
        coach_report=None,
        errors=errors,
        attempts=RETRY_LIMIT,
        coach_failed=True,
    )
