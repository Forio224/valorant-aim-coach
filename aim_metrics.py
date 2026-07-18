r"""
aim_metrics.py
==============
Phase A "Aim Passport": objective, purely-spatial aim metrics for a Valorant clip.

Unlike yolo_mae.py / evaluate_mae.py (which score the DETECTOR against GT), this
module measures the PLAYER's aim. The detected (or labelled) enemy head is taken
as the source of truth for "where the target was", and the crosshair is fixed at
the screen centre (Valorant locks it there). Every metric is a spatial offset
between crosshair and the nearest head, normalised into Head Units (HU = the
target head's own box height), so distance to the enemy cancels out.

Supersedes backend/metrics_calculator.py, which assumed a MOVING crosshair and
emitted arbitrary 0-100 pixel scores; here the crosshair is the fixed centre and
every figure is in Head Units.

Two interchangeable frame sources feed one metrics core:
  - source=gt   : nearest head per frame comes from human CVAT labels (clean
                  measurement, unaffected by detector recall). Needs --xml.
  - source=yolo : nearest head per frame comes from the trained YOLO weights
                  (the product path). Needs --weights, no XML required.

Metrics (all in HU; image y-axis points DOWN):
  dx_hu  = (head_cx - crosshair_x) / head_height   ( + = head right of aim )
  dy_hu  = (head_cy - crosshair_y) / head_height   ( - = head ABOVE aim = aim
                                                       too low = "lazy aiming" )
  radial = hypot(dx_hu, dy_hu)                      per-frame absolute error (MAE)

Aggregates:
  overall MAE   = mean(radial)                      overall crosshair discipline
  duel MAE      = mean(radial | radial <= DUEL_HU)  precision in active engagement
  Y bias        = mean(dy_hu)   signed              vertical placement bias
  X bias        = mean(dx_hu)   signed              horizontal placement bias
  X abs         = mean(|dx_hu|)                     horizontal micro-correction
  tracking std  = std(radial)                       stability while on target

Stage 0: every run is tagged with a mandatory --player-id (per-player from day
one); fps is read from the mp4 container in both modes (in gt mode from the
paired --video; --fps is only a fallback when the mp4 is unavailable).

Usage:
    .\.venv\Scripts\python.exe aim_metrics.py --source gt   --xml dataset1/clip2.xml --video dataset1/clip2.mp4 --player-id author
    .\.venv\Scripts\python.exe aim_metrics.py --source yolo --video dataset/Control/2k_2.mp4 --weights runs/detect/heads_v3/weights/best.pt --player-id author
"""

import argparse
import sys
from typing import List, Optional, Tuple

# Windows consoles default to cp1251 and choke on Cyrillic / math glyphs in the
# passport. Force UTF-8 so the report prints verbatim.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Reuse the CVAT plumbing (GT source). The YOLO adapter is imported lazily inside
# iter_yolo_samples so the gt path never needs torch/ultralytics loaded.
from evaluate_mae import GTBox, parse_cvat_xml

# Stage 0: clip identity + fps + screen geometry (replaces the local
# _crosshair_for_* helpers; fps comes from the mp4 container in both modes).
from engine.clip_context import ClipContext, context_for_gt, context_for_video

# Phase 3 Task 1: ядро геометрии переехало в engine.geometry. Реэкспорт здесь
# сохраняет обратную совместимость всех `from aim_metrics import ...` (тесты и
# внешние импорты); сам CLI и адаптеры источников остаются в этом файле.
from engine.geometry import (  # noqa: F401  (реэкспорт)
    DEFAULT_DUEL_HU,
    MIN_HEAD_PX,
    AimPassport,
    FrameSample,
    Head,
    compute_passport,
    pick_target,
    sample_frame,
)


# ── Report ─────────────────────────────────────────────────────────────────────────

def _y_verdict(y_bias: float) -> str:
    if y_bias < -0.25:
        return "прицел стабильно НИЖЕ голов (lazy aiming, доводка вверх)"
    if y_bias > 0.25:
        return "прицел стабильно ВЫШЕ голов (перекладка)"
    return "вертикаль удерживается на линии голов"


def _context_lines(ctx: ClipContext) -> List[str]:
    """Metadata header: identity always; input-space facts only when supplied."""
    lines = [
        f"  Игрок / клип           : {ctx.player_id} / {ctx.clip_id}",
        f"  FPS / разрешение       : {ctx.fps:g} / {ctx.width}x{ctx.height}"
        f"  (кадров в клипе: {ctx.frame_count})",
    ]
    if ctx.sens is not None or ctx.edpi is not None:
        sens = f"{ctx.sens:g}" if ctx.sens is not None else "?"
        edpi = f"{ctx.edpi:g}" if ctx.edpi is not None else "?"
        lines.append(f"  Сенса / eDPI           : {sens} / {edpi}")
    if ctx.agent is not None or ctx.map_name is not None:
        agent = ctx.agent if ctx.agent is not None else "?"
        map_name = ctx.map_name if ctx.map_name is not None else "?"
        lines.append(f"  Агент / карта          : {agent} / {map_name}")
    return lines


def format_passport(p: AimPassport, label: str, ctx: ClipContext) -> str:
    header = [f"=== АИМ-ПАСПОРТ ({label}) ==="] + _context_lines(ctx)
    if p.frames_measured == 0:
        return "\n".join(header + ["  Нет кадров с целью — нечего измерять."])
    duel = f"{p.duel_mae_hu:.3f} HU" if p.duel_frames else "— (нет активных дуэлей)"
    lines = header + [
        f"  Кадров измерено        : {p.frames_measured}  "
        f"(активных дуэлей <={p.duel_hu:g} HU: {p.duel_frames})",
        f"  Общий MAE прицела      : {p.overall_mae_hu:.3f} HU  (все кадры)",
        f"  MAE в активной дуэли   : {duel}",
        f"  Вертикаль (Y-bias, дуэль): {p.y_bias_hu:+.3f} HU  -> {_y_verdict(p.y_bias_hu)}",
        f"  Горизонт (X-bias, дуэль) : {p.x_bias_hu:+.3f} HU  (|X|={p.x_abs_hu:.3f})",
        f"  Стабильность трекинга  : ±{p.tracking_std_hu:.3f} HU (std, дуэль)",
        f"  Медиана / 95-й перц.   : {p.median_hu:.3f} / {p.p95_hu:.3f} HU (все кадры)",
        "=" * 40,
    ]
    return "\n".join(lines)


# ── Frame sources ────────────────────────────────────────────────────────────────

def _gtbox_to_head(b: GTBox) -> Head:
    return Head(cx=b.cx, cy=b.cy, height_px=b.height)


def iter_gt_samples(xml_path: str,
                    crosshair: Tuple[float, float]) -> List[FrameSample]:
    """Aim samples from human CVAT labels (recall-independent)."""
    gt = parse_cvat_xml(xml_path)
    samples: List[FrameSample] = []
    for frame_idx in sorted(gt.keys()):
        heads = [_gtbox_to_head(b) for b in gt[frame_idx]]
        target = pick_target(heads, crosshair)
        if target is not None:
            samples.append(sample_frame(frame_idx, target, crosshair))
    return samples


def iter_yolo_samples(video_path: str, weights_path: str, conf: float,
                      imgsz: int, crosshair: Tuple[float, float],
                      max_frames: Optional[int]) -> List[FrameSample]:
    """Aim samples from the trained YOLO detector (product path)."""
    import cv2
    from ultralytics import YOLO
    from yolo_mae import detections_from_result

    model = YOLO(weights_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: cannot open video: {video_path}")
        sys.exit(1)

    samples: List[FrameSample] = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if max_frames and frame_idx >= max_frames:
            break
        result = model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)[0]
        heads = [Head(cx=d.center_x, cy=d.center_y, height_px=d.head_height_px)
                 for d in detections_from_result(result)]
        target = pick_target(heads, crosshair)
        if target is not None:
            samples.append(sample_frame(frame_idx, target, crosshair))
        frame_idx += 1
    cap.release()
    return samples


# ── CLI ────────────────────────────────────────────────────────────────────────────

def _build_context(args: argparse.Namespace) -> ClipContext:
    """ClipContext for either source; fps comes from the mp4 in both modes."""
    from pathlib import Path

    meta = dict(player_id=args.player_id, clip_id=args.clip_id,
                fps_override=args.fps, sens=args.sens, edpi=args.edpi,
                agent=args.agent, map_name=args.map)
    if args.source == "gt":
        # The paired mp4 is only an fps source here; without it --fps must cover.
        video = args.video if Path(args.video).is_file() else None
        if video is None:
            print(f"NOTE: видео {args.video} не найдено — fps возьмётся из --fps")
        return context_for_gt(args.xml, video_path=video, **meta)
    return context_for_video(args.video, **meta)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase A aim-passport metrics")
    parser.add_argument("--source", choices=("gt", "yolo"), default="gt",
                        help="head source: human CVAT labels or YOLO detector")
    parser.add_argument("--video", default="dataset1/clip2.mp4")
    parser.add_argument("--xml", default="dataset1/clip2.xml")
    parser.add_argument("--weights",
                        default="runs/detect/heads_v3/weights/best.pt")
    parser.add_argument("--conf", type=float, default=0.4,
                        help="YOLO conf; 0.4 is the holdout knee (FP 16->4, recall ~90%)")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--duel-hu", type=float, default=DEFAULT_DUEL_HU)
    parser.add_argument("--max-frames", type=int, default=None)
    # Stage 0: per-player identity is mandatory; input-space facts are optional.
    parser.add_argument("--player-id", required=True,
                        help="who is playing in this clip (никогда не смешиваем людей)")
    parser.add_argument("--clip-id", default=None,
                        help="clip label; defaults to the xml/video file stem")
    parser.add_argument("--fps", type=float, default=None,
                        help="fallback fps when the mp4 is unavailable (gt mode)")
    parser.add_argument("--sens", type=float, default=None,
                        help="in-game sensitivity (user-supplied, optional)")
    parser.add_argument("--edpi", type=float, default=None)
    parser.add_argument("--agent", default=None)
    parser.add_argument("--map", default=None)
    # Stage 1: print the episode table (gt mode) for manual eye-check.
    parser.add_argument("--episodes", action="store_true",
                        help="печатать таблицу эпизодов (пока только --source gt)")
    # Stage 2: pre-aim placement at enemy appearance (needs episodes).
    parser.add_argument("--placement", action="store_true",
                        help="печатать пре-айм при появлении врага (пока только --source gt)")
    # Stage 4: overshoot/undershoot signature on flick episodes.
    parser.add_argument("--correction", action="store_true",
                        help="печатать сигнатуру коррекции (пока только --source gt)")
    # Stage 5: accumulate this clip into the longitudinal per-player profile.
    parser.add_argument("--save-profile", action="store_true",
                        help="записать клип в продольный профиль игрока и показать его")
    parser.add_argument("--profile-dir", default="profiles",
                        help="каталог JSON-профилей (по умолчанию profiles/)")
    # Stage 6: evidence-tagged JSON contract for the VLM coach (Phase B).
    parser.add_argument("--report-json", default=None, metavar="FILE",
                        help="записать evidence-JSON портрет в файл ('-' = stdout)")
    # Stage B0: annotated evidence frames (shared input for the VLM coach + UI).
    parser.add_argument("--evidence-frames", default=None, metavar="DIR",
                        help="вырезать и аннотировать кадры-улики из --video в каталог")
    args = parser.parse_args()

    try:
        ctx = _build_context(args)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    crosshair = ctx.crosshair
    if args.source == "gt":
        samples = iter_gt_samples(args.xml, crosshair)
        label = f"gt: {args.xml}"
    else:
        samples = iter_yolo_samples(args.video, args.weights, args.conf,
                                    args.imgsz, crosshair, args.max_frames)
        label = f"yolo: {args.video}"

    print(f"Crosshair (screen centre): ({crosshair[0]:.0f}, {crosshair[1]:.0f})\n")
    passport = compute_passport(samples, duel_hu=args.duel_hu)
    print(format_passport(passport, label, ctx))

    # Stage 3: spread-first consistency verdict, front and centre of the portrait.
    from engine.metrics.consistency import compute_consistency, format_consistency
    print()
    print(format_consistency(compute_consistency(samples, duel_hu=args.duel_hu)))

    needs_episodes = (args.episodes or args.placement or args.correction
                      or args.save_profile or args.report_json
                      or args.evidence_frames)
    if needs_episodes:
        if args.source != "gt":
            print("\n--episodes/--placement/--correction/--save-profile/"
                  "--report-json/--evidence-frames пока поддерживаются"
                  " только для --source gt")
            sys.exit(1)
        from engine.episodes import episodes_for_gt, format_episodes
        episodes = episodes_for_gt(args.xml, ctx, duel_hu=args.duel_hu)
        if args.episodes:
            print()
            print(format_episodes(episodes, ctx))
        if args.placement:
            from engine.metrics.placement import compute_placement, format_placement
            print()
            print(format_placement(compute_placement(episodes, ctx), ctx))
        if args.correction:
            from engine.metrics.correction import (compute_correction,
                                                   format_correction)
            from engine.metrics.flick_phase import (compute_flick_phases,
                                                    format_flick_phases)
            print()
            print(format_correction(compute_correction(episodes, ctx,
                                                        duel_hu=args.duel_hu), ctx))
            print()
            print(format_flick_phases(compute_flick_phases(episodes, ctx), ctx))
        if args.save_profile:
            from engine.profile_store import (aggregate_profile,
                                              build_clip_record, format_profile,
                                              load_player, save_clip)
            record = build_clip_record(ctx, samples, episodes,
                                       duel_hu=args.duel_hu)
            path = save_clip(args.profile_dir, ctx, record)
            print(f"\nКлип записан в профиль: {path}\n")
            print(format_profile(aggregate_profile(
                load_player(args.profile_dir, ctx.player_id))))
        if args.report_json or args.evidence_frames:
            from engine.profile_store import aggregate_profile, load_player
            from engine.report import build_report, report_to_json
            doc = load_player(args.profile_dir, ctx.player_id)
            profile = aggregate_profile(doc) if doc else None
            report = build_report(ctx, samples, episodes,
                                  duel_hu=args.duel_hu, profile=profile)
        if args.report_json:
            text = report_to_json(report)
            if args.report_json == "-":
                print(f"\n{text}")
            else:
                from pathlib import Path
                out = Path(args.report_json)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                print(f"\nEvidence-JSON записан: {args.report_json}")
        if args.evidence_frames:
            from engine.evidence_frames import render_evidence_frames
            try:
                paths = render_evidence_frames(args.video, report,
                                               args.evidence_frames)
            except ValueError as e:
                print(f"ERROR: {e}")
                sys.exit(1)
            print(f"\nКадры-улики записаны: {len(paths)} шт."
                  f" -> {args.evidence_frames}")


if __name__ == "__main__":
    main()
