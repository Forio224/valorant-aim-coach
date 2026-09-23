# -*- coding: utf-8 -*-
"""Stage B3: продуктовый пайплайн — видео → YOLO → движок → коуч.

Заменяет легаси-путь «сырые кадры → Claude с общим промптом» (vlm_client):
числа считает ТОЛЬКО движок Phase A, Claude их объясняет (B1) и проходит
groundedness-валидацию (B2).

Шаги (статусы для БД/фронта):
  DETECTING  — YOLO heads_v3 по каждому кадру (conf=0.4 — колено холдаута,
               калибровка закрыта);
  MEASURING  — сэмплы паспорта + эпизоды + findings + продольный профиль
               + аннотированные кадры-улики;
  COACHING   — CoachClient + run_coach_validated; провал коуча НЕ роняет
               пайплайн — отдаётся частичный результат (coach_failed).

Детектор и коуч-клиент инжектируются (тесты гоняют синтетику без torch/API).
"""
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from engine.geometry import DEFAULT_DUEL_HU, Head
from engine.attribution import attribute_targets
from engine.clip_context import context_for_video
from engine.episodes import HeadsByFrame, segment_episodes
from engine.evidence_frames import DEFAULT_EVIDENCE_CAP, render_evidence_frames
from engine.profile_store import (aggregate_profile, build_clip_record,
                                  load_player, save_clip)
from engine.platform_profile import PlatformProfile, resolve_profile
from engine.report import build_report

logger = logging.getLogger(__name__)

STATUS_DETECTING = "DETECTING"
STATUS_MEASURING = "MEASURING"
STATUS_COACHING = "COACHING"

DEFAULT_WEIGHTS = "runs/detect/heads_v3/weights/best.pt"
DEFAULT_CONF = 0.4            # колено холдаута (FP 16->4, recall ~90%)
DEFAULT_IMGSZ = 1280
DEFAULT_PROFILE_DIR = "profiles"
DEFAULT_COACH_MAX_IMAGES = 5  # кап цены VLM; валидатор B2 страхует качество
DEFAULT_TARGET_COLOUR = "orange"   # типовой цвет целей в тренажёрах

# Платформы, чьи клипы разбираются цветовым детектором, а не YOLO по головам.
TRAINER_PLATFORMS = ("kovaaks", "aimbeast")

YOLO_SOURCE_NAME = "yolo_heads"

Detector = Callable[[str], HeadsByFrame]
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class PipelineConfig:
    """Продуктовые ручки; всё, что калибровано в Phase A, здесь по умолчанию."""
    weights_path: str = DEFAULT_WEIGHTS
    conf: float = DEFAULT_CONF
    imgsz: int = DEFAULT_IMGSZ
    duel_hu: float = DEFAULT_DUEL_HU
    profile_dir: str = DEFAULT_PROFILE_DIR
    evidence_cap: int = DEFAULT_EVIDENCE_CAP
    coach_max_images: int = DEFAULT_COACH_MAX_IMAGES
    target_colour: str = DEFAULT_TARGET_COLOUR   # пресет цвета целей тренажёра

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        return cls(
            weights_path=os.getenv("YOLO_WEIGHTS", DEFAULT_WEIGHTS),
            profile_dir=os.getenv("PROFILE_DIR", DEFAULT_PROFILE_DIR),
            coach_max_images=int(os.getenv("COACH_MAX_IMAGES",
                                           str(DEFAULT_COACH_MAX_IMAGES))),
            target_colour=os.getenv("TRAINER_TARGET_COLOUR",
                                    DEFAULT_TARGET_COLOUR),
        )


@dataclass(frozen=True)
class PipelineResult:
    """Всё, что нужно БД и фронту: движок всегда, коуч — если прошёл B2."""
    evidence_report: dict
    evidence_frames: List[str]          # пути к jpg-уликам (str для JSON)
    coach_report: Optional[dict]
    coach_failed: bool
    coach_errors: List[str]
    coach_attempts: int


# ── Продуктовый источник голов (yolo) ────────────────────────────────────────

def detect_heads_yolo(video_path: str, config: PipelineConfig) -> HeadsByFrame:
    """ВСЕ головы на каждом кадре — эпизодам нужна полная сцена, не цель."""
    import cv2
    from ultralytics import YOLO
    from yolo_mae import detections_from_result

    model = YOLO(config.weights_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"не удалось открыть видео: {video_path}")
    heads_by_frame: Dict[int, List[Head]] = {}
    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            result = model.predict(frame, imgsz=config.imgsz,
                                   conf=config.conf, verbose=False)[0]
            heads = [Head(cx=d.center_x, cy=d.center_y,
                          height_px=d.head_height_px)
                     for d in detections_from_result(result)]
            if heads:
                heads_by_frame[frame_idx] = heads
            frame_idx += 1
    finally:
        cap.release()
    return heads_by_frame


def profile_for(training_platform: Optional[str]) -> PlatformProfile:
    """Пороги движка под источник клипа; неизвестное — валорантовые."""
    return resolve_profile(training_platform)


def default_detector_for(training_platform: Optional[str],
                         config: PipelineConfig) -> Detector:
    """Источник целей по платформе.

    Веса heads_v3 обучены на головах Valorant и на сферах тренажёра не
    работают, поэтому клип тренажёра по умолчанию идёт в цветовой детектор.
    Явно переданный `detector` эту логику отменяет — на нём держатся тесты
    и CLI.
    """
    if training_platform in TRAINER_PLATFORMS:
        from backend.trainer_target_detector import (TargetParams,
                                                     make_trainer_detector)
        return make_trainer_detector(
            TargetParams.from_preset(config.target_colour))

    def yolo_detector(path: str) -> HeadsByFrame:
        return detect_heads_yolo(path, config)
    yolo_detector.source = YOLO_SOURCE_NAME
    return yolo_detector


# ── Лог аим-тренажёра: второй источник истины к видео ────────────────────────

def _shots_block(stats_path: Optional[str], ctx, episodes) -> Optional[dict]:
    """Секция попаданий из лога прогона; None, если логу здесь не место.

    Любая беда с файлом деградирует в блок с причиной, а не в падение
    сессии: разбор по видео остаётся полезным и без статистики.
    """
    if not stats_path or ctx.training_platform not in TRAINER_PLATFORMS:
        return None

    from engine.metrics.shots import compute_shot_metrics
    from engine.trainer_stats import TrainerSession, parse_stats
    from engine.trainer_stats.sync import (SyncResult, estimate_offset,
                                           target_loss_times)
    try:
        session = parse_stats(stats_path, ctx.training_platform)
        sync = estimate_offset(
            target_loss_times(episodes, ctx.fps),
            [e.t_seconds for e in session.events])
    except Exception as exc:                      # noqa: BLE001 — деградация
        logger.exception("лог тренажёра не разобран, отдаём разбор без него")
        session = TrainerSession(platform=ctx.training_platform)
        sync = SyncResult(None, 0, 0,
                          f"лог тренажёра не разобран: {exc}")
    return compute_shot_metrics(session, sync).to_report_block()


# ── Коуч (B1+B2), изолированный от пайплайна ─────────────────────────────────

def _run_coach(coach_client, report: dict, frame_paths: Sequence,
               config: PipelineConfig):
    """Любая ошибка коуча -> деградация coach_failed, движок не теряется."""
    from coach.drill_catalog import finalize_plan
    from coach.validate import run_coach_validated
    try:
        client = coach_client
        if client is None:
            from coach.providers.factory import create_coach_client
            client = create_coach_client()
        result = run_coach_validated(
            client, report, list(frame_paths)[: config.coach_max_images])
    except Exception as exc:                      # noqa: BLE001 — деградация
        logger.exception("коуч упал, отдаём частичный результат")
        return None, [f"коуч упал: {exc}"], 0, True
    if result.coach_report is None:
        return None, result.errors, result.attempts, result.coach_failed
    coach_dict = result.coach_report.model_dump()
    plan = finalize_plan(result.coach_report.drills,
                         report.get("findings", []),
                         report.get("external_benchmark"))
    coach_dict["drills"] = [d.model_dump() for d in plan.drills]
    coach_dict["caveats"] = coach_dict["caveats"] + plan.extra_caveats
    return coach_dict, result.errors, result.attempts, result.coach_failed


# ── Точка входа ──────────────────────────────────────────────────────────────

def run_pipeline(video_path: str, player_id: str, *,
                 clip_id: Optional[str] = None,
                 sens: Optional[float] = None,
                 edpi: Optional[float] = None,
                 agent: Optional[str] = None,
                 map_name: Optional[str] = None,
                 training_platform: Optional[str] = None,
                 config: Optional[PipelineConfig] = None,
                 evidence_dir: str,
                 on_status: Optional[StatusCallback] = None,
                 detector: Optional[Detector] = None,
                 coach_client=None,
                 history_provider: Optional[Callable] = None,
                 steam_id: Optional[str] = None,
                 external_fetcher: Optional[Callable] = None,
                 stats_path: Optional[str] = None
                 ) -> PipelineResult:
    """Полный продуктовый прогон одного клипа одного игрока."""
    cfg = config or PipelineConfig.from_env()
    notify = on_status or (lambda status: None)

    try:
        ctx = context_for_video(str(video_path), player_id=player_id,
                                clip_id=clip_id, sens=sens, edpi=edpi,
                                agent=agent, map_name=map_name,
                                training_platform=training_platform)
    except ValueError as exc:
        # cv2 не открыл контейнер: игроку нужно человеческое объяснение.
        raise ValueError(
            "не удалось прочитать видео — файл повреждён или это не видео"
        ) from exc

    # Пороги движка зависят от источника клипа: валорантовая калибровка
    # сферам тренажёра не наследуется (engine/platform_profile.py).
    profile_thresholds = profile_for(ctx.training_platform)
    duel_hu = profile_thresholds.duel_hu

    notify(STATUS_DETECTING)
    detect = detector or default_detector_for(ctx.training_platform, cfg)
    heads_by_frame = detect(str(video_path))

    notify(STATUS_MEASURING)
    episodes = segment_episodes(heads_by_frame, ctx, duel_hu=duel_hu)
    # Фаза 3: атрибуция цели по намерению вместо «ближайшей на каждом кадре» —
    # consistency/bias/профиль кормятся сэмплами с назначенным треком (спорные
    # кадры исключены из механики, но честно посчитаны в consistency).
    attribution = attribute_targets(episodes, ctx, duel_hu=duel_hu)
    samples = [s for s in attribution.samples if s.track_id is not None]

    # Продольное накопление ДО отчёта — свежий клип входит в свой же профиль.
    record = build_clip_record(ctx, samples, episodes, duel_hu=duel_hu)
    save_clip(cfg.profile_dir, ctx, record)
    profile = aggregate_profile(load_player(cfg.profile_dir, ctx.player_id))

    provider = history_provider or (lambda pid, cid: [])
    drill_history = provider(player_id, ctx.clip_id)

    # Внешний ранк KovaaK's: чужой недокументированный API — сбой любого
    # рода деградирует в «данных нет», сессию не роняет (контракт спеки).
    external_block, external_reason = None, None
    if steam_id:
        fetcher = external_fetcher
        if fetcher is None:
            from backend.services.kovaaks_client import (
                fetch_benchmark_progress)
            fetcher = fetch_benchmark_progress
        try:
            external_block, external_reason = fetcher(steam_id)
        except Exception:                  # noqa: BLE001 — деградация
            logger.exception("внешний ранк KovaaK's не получен")
            external_block, external_reason = None, "api_error"

    report = build_report(ctx, samples, episodes, duel_hu=duel_hu,
                          profile=profile, drill_history=drill_history,
                          attribution=attribution,
                          external_benchmark=external_block,
                          external_unavailable_reason=external_reason,
                          shots=_shots_block(stats_path, ctx, episodes))
    frame_paths = render_evidence_frames(str(video_path), report,
                                         evidence_dir, cap=cfg.evidence_cap)

    notify(STATUS_COACHING)
    if not samples:
        # Пустой клип: коучу нечего объяснять — не тратим вызов VLM.
        coach_report, errors, attempts, failed = None, [
            "в клипе не найдено ни одной головы врага — коучу нечего "
            "объяснять; проверьте, что это запись боя Valorant"
        ], 0, True
    else:
        coach_report, errors, attempts, failed = _run_coach(
            coach_client, report, frame_paths, cfg)

    return PipelineResult(
        evidence_report=report,
        evidence_frames=[str(p) for p in frame_paths],
        coach_report=coach_report,
        coach_failed=failed,
        coach_errors=errors,
        coach_attempts=attempts,
    )
