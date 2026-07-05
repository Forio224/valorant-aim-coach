"""Stage B0: materialise evidence into annotated JPEG frames.

The report (schema >= 1.1) carries anchor-frame geometry on every evidence
entry, so the head box is reconstructed in pixels purely from the JSON —
crosshair = fixed screen centre, head centre = centre + d*_hu × head height.
The rendered frames serve two consumers: the VLM coach (situational context
for its advice) and the frontend (proof shown next to each finding).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from aim_metrics import MIN_HEAD_PX

DEFAULT_EVIDENCE_CAP = 10      # max frames per clip (VLM image budget)
JPEG_QUALITY = 90
MIN_ARROW_PX = 6.0             # skip the offset arrow when aim is on target

BOX_COLOR = (80, 220, 80)      # BGR: head box
CROSSHAIR_COLOR = (60, 160, 255)
ARROW_COLOR = (0, 200, 255)
LABEL_TEXT_COLOR = (235, 235, 235)
LABEL_BG_COLOR = (12, 12, 12)


@dataclass(frozen=True)
class EvidenceTarget:
    """One frame worth rendering: merged notes of every finding citing it."""
    frame_idx: int
    time_s: float
    dx_hu: float
    dy_hu: float
    head_height_px: float
    notes: Tuple[str, ...]
    metrics: Tuple[str, ...]
    window_only: bool          # cited only as a duel-window anchor


# ── Geometry (inverse of aim_metrics.sample_frame) ───────────────────────────

def head_box_px(dx_hu: float, dy_hu: float, head_height_px: float,
                width: int, height: int) -> Tuple[float, float, float]:
    """HU offsets -> pixel head centre + drawable box height.

    Must mirror sample_frame's tiny-head guard (MIN_HEAD_PX) exactly,
    otherwise reconstructed positions drift for degenerate boxes.
    """
    hu = max(head_height_px, MIN_HEAD_PX)
    return (width / 2.0 + dx_hu * hu, height / 2.0 + dy_hu * hu, hu)


# ── Target collection ────────────────────────────────────────────────────────

def _entry_geometry(entry: dict, metric: str) -> Tuple[float, float, float]:
    try:
        return (float(entry["dx_hu"]), float(entry["dy_hu"]),
                float(entry["head_height_px"]))
    except KeyError as e:
        raise ValueError(
            f"evidence-запись метрики «{metric}» не несёт геометрию ({e}) — "
            f"нужен отчёт schema >= 1.1, перегенерируйте --report-json"
        ) from e


def collect_evidence_targets(report: dict,
                             cap: int = DEFAULT_EVIDENCE_CAP,
                             ) -> List[EvidenceTarget]:
    """Dedupe evidence frames across findings, merge notes, cap the count.

    Point evidence (placement births, correction flips) is preferred over
    duel-window anchors when the cap forces a choice.
    """
    grouped: Dict[int, dict] = {}
    for finding in report.get("findings", []):
        metric = finding["metric"]
        for entry in finding.get("evidence", []):
            frame = entry.get("frame", entry.get("frame_start"))
            if frame is None:
                continue
            dx, dy, hh = _entry_geometry(entry, metric)
            g = grouped.setdefault(frame, {
                "time_s": float(entry["time_s"]),
                "geom": (dx, dy, hh), "notes": [], "metrics": [],
                "point": False,
            })
            note = entry.get("note")
            if note and note not in g["notes"]:
                g["notes"].append(note)
            if metric not in g["metrics"]:
                g["metrics"].append(metric)
            if "frame" in entry:
                g["point"] = True

    targets = [
        EvidenceTarget(frame_idx=frame, time_s=g["time_s"],
                       dx_hu=g["geom"][0], dy_hu=g["geom"][1],
                       head_height_px=g["geom"][2],
                       notes=tuple(g["notes"]), metrics=tuple(g["metrics"]),
                       window_only=not g["point"])
        for frame, g in grouped.items()
    ]
    chosen = sorted(targets, key=lambda t: (t.window_only, t.frame_idx))[:cap]
    return sorted(chosen, key=lambda t: t.frame_idx)


# ── Annotation ───────────────────────────────────────────────────────────────

def _load_font(size: int):
    """Cyrillic-capable font; PIL's built-in default lacks the glyphs."""
    from PIL import ImageFont
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_label(img: np.ndarray, target: EvidenceTarget) -> np.ndarray:
    """Text panel via PIL: cv2.putText cannot draw the Russian notes."""
    import cv2
    from PIL import Image, ImageDraw

    h_img = img.shape[0]
    size = max(14, h_img // 50)
    pad = size // 2
    lines = [f"кадр {target.frame_idx} ({target.time_s:.2f} c)   "
             f"dx {target.dx_hu:+.2f} / dy {target.dy_hu:+.2f} HU   "
             f"[{', '.join(target.metrics)}]"]
    lines += [f"• {note}" for note in target.notes]

    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    font = _load_font(size)
    widths = [draw.textlength(line, font=font) for line in lines]
    panel_h = pad * 2 + len(lines) * (size + pad // 2)
    draw.rectangle((0, 0, max(widths) + pad * 2, panel_h),
                   fill=LABEL_BG_COLOR[::-1])
    for i, line in enumerate(lines):
        draw.text((pad, pad + i * (size + pad // 2)), line,
                  fill=LABEL_TEXT_COLOR[::-1], font=font)
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def annotate_frame(img: np.ndarray, target: EvidenceTarget) -> np.ndarray:
    """Crosshair-centre marker, head box, offset arrow, text label."""
    import cv2

    h_img, w_img = img.shape[:2]
    cx, cy, box_h = head_box_px(target.dx_hu, target.dy_hu,
                                target.head_height_px, w_img, h_img)
    centre = (round(w_img / 2), round(h_img / 2))
    head_pt = (round(cx), round(cy))
    half = box_h / 2.0

    out = img.copy()
    cv2.rectangle(out, (round(cx - half), round(cy - half)),
                  (round(cx + half), round(cy + half)), BOX_COLOR, 2)
    cv2.drawMarker(out, centre, CROSSHAIR_COLOR, cv2.MARKER_CROSS,
                   markerSize=max(round(h_img * 0.03), 12), thickness=2)
    if float(np.hypot(cx - centre[0], cy - centre[1])) > MIN_ARROW_PX:
        cv2.arrowedLine(out, centre, head_pt, ARROW_COLOR, 2, tipLength=0.15)
    return _draw_label(out, target)


# ── Rendering entry point ────────────────────────────────────────────────────

def render_evidence_frames(video_path: str, report: dict, out_dir: str,
                           cap: int = DEFAULT_EVIDENCE_CAP) -> List[Path]:
    """Extract + annotate every evidence frame of a report from its video."""
    import cv2

    targets = collect_evidence_targets(report, cap=cap)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"не удалось открыть видео: {video_path}")
    paths: List[Path] = []
    try:
        for target in targets:
            capture.set(cv2.CAP_PROP_POS_FRAMES, target.frame_idx)
            ok, frame = capture.read()
            if not ok:
                raise ValueError(
                    f"кадр {target.frame_idx} не читается из {video_path} — "
                    f"отчёт от другого видео?")
            path = out / f"frame_{target.frame_idx:06d}.jpg"
            cv2.imwrite(str(path), annotate_frame(frame, target),
                        [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            paths.append(path)
    finally:
        capture.release()
    return paths
