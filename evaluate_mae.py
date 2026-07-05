"""
evaluate_mae.py
===============
MAE evaluation: CentroidHeadDetector vs CVAT ground truth.

Usage:
    python evaluate_mae.py
    python evaluate_mae.py --preset yellow --video dataset1/output_clip.mp4 --xml dataset1/output_clip.xml
    python evaluate_mae.py --debug          # shows live debug window
    python evaluate_mae.py --max-frames 200 # quick smoke test
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, "backend")
from centroid_head_detector import CentroidHeadDetector, HSV_PRESETS, HeadDetection


# ── Ground truth types ─────────────────────────────────────────────────────────

@dataclass
class GTBox:
    cx: float
    cy: float
    width: float
    height: float  # used as head_height_px reference for HU normalisation


GroundTruth = Dict[int, List[GTBox]]  # frame_index → visible GT boxes


# ── XML parser ─────────────────────────────────────────────────────────────────

def parse_cvat_xml(xml_path: str) -> GroundTruth:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    gt: GroundTruth = defaultdict(list)

    for track in root.findall("track"):
        for box in track.findall("box"):
            if box.attrib.get("outside", "0") == "1":
                continue
            frame = int(box.attrib["frame"])
            xtl = float(box.attrib["xtl"])
            ytl = float(box.attrib["ytl"])
            xbr = float(box.attrib["xbr"])
            ybr = float(box.attrib["ybr"])
            gt[frame].append(GTBox(
                cx=(xtl + xbr) / 2.0,
                cy=(ytl + ybr) / 2.0,
                width=xbr - xtl,
                height=ybr - ytl,
            ))

    return gt


# ── Matching: nearest GT → detection ──────────────────────────────────────────

def match_detections(
    gt_boxes: List[GTBox],
    detections: List[HeadDetection],
    max_dist_px: float = 50.0,
) -> Tuple[List[Tuple[GTBox, HeadDetection]], List[GTBox], List[HeadDetection]]:
    """Greedy nearest-neighbour matching (sufficient for ≤4 enemies per frame)."""
    if not gt_boxes or not detections:
        return [], gt_boxes[:], detections[:]

    used_det: set = set()
    matched = []
    unmatched_gt = []

    for gt in gt_boxes:
        best_dist = float("inf")
        best_idx = -1
        for i, det in enumerate(detections):
            if i in used_det:
                continue
            dist = np.hypot(det.center_x - gt.cx, det.center_y - gt.cy)
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        if best_idx >= 0 and best_dist <= max_dist_px:
            matched.append((gt, detections[best_idx]))
            used_det.add(best_idx)
        else:
            unmatched_gt.append(gt)

    unmatched_det = [d for i, d in enumerate(detections) if i not in used_det]
    return matched, unmatched_gt, unmatched_det


# ── Main evaluation loop ───────────────────────────────────────────────────────

def evaluate(
    video_path: str,
    xml_path: str,
    preset: str,
    max_frames: Optional[int],
    show_debug: bool,
) -> None:
    gt = parse_cvat_xml(xml_path)
    annotated_frames = sorted(gt.keys())

    if not annotated_frames:
        print("ERROR: no annotated frames found in XML.")
        sys.exit(1)

    total_gt = sum(len(v) for v in gt.values())
    print(f"Loaded {total_gt} GT boxes across {len(annotated_frames)} frames "
          f"(frames {annotated_frames[0]}–{annotated_frames[-1]})")

    detector = CentroidHeadDetector(HSV_PRESETS[preset])

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: cannot open video: {video_path}")
        sys.exit(1)

    vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video: {vid_w}×{vid_h}, {total_vid_frames} frames, preset={preset}\n")

    hu_errors: List[float] = []
    px_errors: List[float] = []
    misses = 0
    false_positives = 0
    flashed_frames = 0
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

        result = detector.detect(frame)

        if result.frame_quality == "FLASH":
            flashed_frames += 1
            frame_idx += 1
            continue

        gt_boxes = gt[frame_idx]
        matched, unmatched_gt, unmatched_det = match_detections(gt_boxes, result.detections)

        for gt_box, det in matched:
            head_hu = max(gt_box.height, 1.0)
            px_err = np.hypot(det.center_x - gt_box.cx, det.center_y - gt_box.cy)
            hu_errors.append(px_err / head_hu)
            px_errors.append(px_err)

        misses += len(unmatched_gt)
        false_positives += len(unmatched_det)

        if show_debug:
            dbg = detector.draw_debug(frame)
            for gt_box in gt_boxes:
                cv2.circle(dbg, (int(gt_box.cx), int(gt_box.cy)), 6, (0, 255, 0), 2)
                cv2.rectangle(
                    dbg,
                    (int(gt_box.cx - gt_box.width / 2), int(gt_box.cy - gt_box.height / 2)),
                    (int(gt_box.cx + gt_box.width / 2), int(gt_box.cy + gt_box.height / 2)),
                    (0, 255, 0), 1,
                )
            cv2.imshow("Eval  green=GT  yellow=detected", dbg)
            if cv2.waitKey(30) & 0xFF == ord('q'):
                break

        frame_idx += 1

    cap.release()
    if show_debug:
        cv2.destroyAllWindows()

    # ── Report ─────────────────────────────────────────────────────────────────
    detected = len(hu_errors)
    print("=" * 55)
    print("  MAE EVALUATION REPORT")
    print("=" * 55)
    print(f"  GT boxes total        : {total_gt}")
    print(f"  Matched (detected)    : {detected}")
    print(f"  Missed (false neg)    : {misses}")
    print(f"  False positives       : {false_positives}")
    print(f"  Flashed frames skipped: {flashed_frames}")
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


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate CentroidHeadDetector MAE")
    parser.add_argument("--video",      default="dataset1/output_clip.mp4")
    parser.add_argument("--xml",        default="dataset1/output_clip.xml")
    parser.add_argument("--preset",     default="yellow", choices=list(HSV_PRESETS.keys()))
    parser.add_argument("--max-frames", type=int, default=None,
                        help="Stop after N frames (quick smoke test)")
    parser.add_argument("--debug",      action="store_true",
                        help="Show live debug window (green=GT, yellow=detected)")
    args = parser.parse_args()

    evaluate(
        video_path=args.video,
        xml_path=args.xml,
        preset=args.preset,
        max_frames=args.max_frames,
        show_debug=args.debug,
    )
