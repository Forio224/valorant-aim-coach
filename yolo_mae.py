r"""
yolo_mae.py
===========
MAE evaluation: trained YOLO head detector vs CVAT ground truth.

The YOLO replacement for evaluate_mae.py. Instead of the HSV CentroidHeadDetector
(which capped at ~1% detection and chased ability VFX), this runs the fine-tuned
YOLO weights and reports the same metrics so the two approaches are directly
comparable:
    - MAE in Head Units (px error normalised by GT head height)
    - MAE in pixels
    - miss rate (false negatives) and false positives

Reuses parse_cvat_xml / GTBox / match_detections from evaluate_mae.py.

Usage:
    .\.venv\Scripts\python.exe yolo_mae.py
    .\.venv\Scripts\python.exe yolo_mae.py --conf 0.25 --imgsz 1280
    .\.venv\Scripts\python.exe yolo_mae.py --max-frames 200   # quick smoke test
"""

import argparse
import sys
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

# Reuse the ground-truth plumbing from the HSV evaluator so both detectors are
# scored by identical matching / HU-normalisation logic.
from evaluate_mae import GTBox, match_detections, parse_cvat_xml

from ultralytics import YOLO


# ── Detection adapter ───────────────────────────────────────────────────────────

@dataclass
class YoloDetection:
    """Minimal detection compatible with match_detections (duck-typed on
    center_x / center_y). head_height_px kept for parity / debugging."""
    center_x: float
    center_y: float
    head_height_px: float
    confidence: float


def detections_from_result(result) -> List[YoloDetection]:
    """Convert an ultralytics Results object (single frame) into YoloDetection list."""
    detections: List[YoloDetection] = []
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return detections

    xywh = boxes.xywh.cpu().numpy()         # (N, 4): cx, cy, w, h in pixels
    confs = boxes.conf.cpu().numpy()        # (N,)
    for (cx, cy, _w, h), conf in zip(xywh, confs):
        detections.append(YoloDetection(
            center_x=float(cx),
            center_y=float(cy),
            head_height_px=float(h),
            confidence=float(conf),
        ))
    return detections


# ── Main evaluation loop ───────────────────────────────────────────────────────

def evaluate(
    video_path: str,
    xml_path: str,
    weights_path: str,
    conf: float,
    imgsz: int,
    max_dist_px: float,
    max_frames: Optional[int],
) -> None:
    gt = parse_cvat_xml(xml_path)
    annotated_frames = sorted(gt.keys())

    if not annotated_frames:
        print("ERROR: no annotated frames found in XML.")
        sys.exit(1)

    total_gt = sum(len(v) for v in gt.values())
    print(f"Loaded {total_gt} GT boxes across {len(annotated_frames)} frames "
          f"(frames {annotated_frames[0]}–{annotated_frames[-1]})")

    model = YOLO(weights_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: cannot open video: {video_path}")
        sys.exit(1)

    vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video: {vid_w}×{vid_h}, {total_vid_frames} frames | "
          f"weights={weights_path} conf={conf} imgsz={imgsz}\n")

    hu_errors: List[float] = []
    px_errors: List[float] = []
    misses = 0
    false_positives = 0
    annotated_set = set(annotated_frames)

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if max_frames and frame_idx >= max_frames:
            break

        if frame_idx not in annotated_set:
            frame_idx += 1
            continue

        result = model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)[0]
        detections = detections_from_result(result)

        gt_boxes = gt[frame_idx]
        matched, unmatched_gt, unmatched_det = match_detections(
            gt_boxes, detections, max_dist_px=max_dist_px,
        )

        for gt_box, det in matched:
            head_hu = max(gt_box.height, 1.0)
            px_err = np.hypot(det.center_x - gt_box.cx, det.center_y - gt_box.cy)
            hu_errors.append(px_err / head_hu)
            px_errors.append(px_err)

        misses += len(unmatched_gt)
        false_positives += len(unmatched_det)

        frame_idx += 1

    cap.release()

    # ── Report ─────────────────────────────────────────────────────────────────
    detected = len(hu_errors)
    print("=" * 55)
    print("  YOLO MAE EVALUATION REPORT")
    print("=" * 55)
    print(f"  GT boxes total        : {total_gt}")
    print(f"  Matched (detected)    : {detected}")
    print(f"  Missed (false neg)    : {misses}")
    print(f"  False positives       : {false_positives}")
    print()

    if hu_errors:
        print(f"  MAE  (Head Units)     : {np.mean(hu_errors):.4f} HU")
        print(f"  MAE  (pixels)         : {np.mean(px_errors):.1f} px")
        print(f"  Median error (HU)     : {np.median(hu_errors):.4f} HU")
        print(f"  95th pct error (HU)   : {np.percentile(hu_errors, 95):.4f} HU")
        print(f"  Max error (HU)        : {np.max(hu_errors):.4f} HU")
    else:
        print("  No matches — detector found nothing on annotated frames.")

    if total_gt > 0:
        print(f"\n  Detection rate        : {detected / total_gt * 100:.1f}%")
        print(f"  Miss rate             : {misses / total_gt * 100:.1f}%")
    print("=" * 55)


# ── CLI ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate YOLO head detector MAE")
    parser.add_argument("--video",   default="dataset1/output_clip.mp4")
    parser.add_argument("--xml",     default="dataset1/output_clip.xml")
    parser.add_argument("--weights", default="runs/detect/heads_v1-2/weights/best.pt")
    parser.add_argument("--conf",    type=float, default=0.3,
                        help="YOLO confidence threshold")
    parser.add_argument("--imgsz",   type=int, default=1280,
                        help="Inference image size (match training)")
    parser.add_argument("--max-dist", type=float, default=50.0,
                        help="Max px distance for GT↔detection match")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="Stop after N frames (quick smoke test)")
    args = parser.parse_args()

    evaluate(
        video_path=args.video,
        xml_path=args.xml,
        weights_path=args.weights,
        conf=args.conf,
        imgsz=args.imgsz,
        max_dist_px=args.max_dist,
        max_frames=args.max_frames,
    )
