r"""
diagnose_red.py
===============
One-off diagnostic: is the YOLO head model blind to a red-outline clip, or is
the CVAT ground truth on that clip misaligned/broken?

Renders, for a handful of annotated frames:
  - GT boxes  (GREEN)
  - YOLO predictions at a LOW conf threshold (RED + confidence label)
Saves both a full-frame overlay and a 2x-zoomed crop around each GT head
(small ~20px heads are unreadable at full 1080p), plus prints a quantitative
summary so the verdict does not rely on eyeballing alone.

Usage:
    .\.venv\Scripts\python.exe diagnose_red.py
    .\.venv\Scripts\python.exe diagnose_red.py --video dataset/Control/2k_2.mp4 --xml dataset/Control/2k_2.xml
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from evaluate_mae import parse_cvat_xml
from ultralytics import YOLO

GREEN = (0, 255, 0)
RED = (0, 0, 255)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video",   default="dataset/Control/2k_2.mp4")
    ap.add_argument("--xml",     default="dataset/Control/2k_2.xml")
    ap.add_argument("--weights", default="runs/detect/heads_v1-2/weights/best.pt")
    ap.add_argument("--conf",    type=float, default=0.10,
                    help="LOW threshold to surface any latent detection")
    ap.add_argument("--imgsz",   type=int, default=1280)
    ap.add_argument("--n",       type=int, default=8, help="frames to render")
    ap.add_argument("--out",     default="diag_out")
    args = ap.parse_args()

    gt = parse_cvat_xml(args.xml)
    annotated = sorted(gt.keys())
    if not annotated:
        print("ERROR: no GT frames")
        sys.exit(1)

    # Evenly sample N annotated frames across the timeline.
    idxs = np.linspace(0, len(annotated) - 1, min(args.n, len(annotated)))
    sample = sorted({annotated[int(round(i))] for i in idxs})

    out = Path(args.out)
    out.mkdir(exist_ok=True)

    model = YOLO(args.weights)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"ERROR: cannot open {args.video}")
        sys.exit(1)

    sample_set = set(sample)
    # Aggregate signal across ALL annotated frames (not just rendered ones).
    total_preds = 0
    max_conf_overall = 0.0
    frames_with_any_pred = 0
    n_annotated_scanned = 0

    print(f"Clip: {args.video}")
    print(f"GT frames: {len(annotated)}  | rendering {len(sample)} frames "
          f"| conf>={args.conf}\n")
    print(f"{'frame':<8}{'#GT':<6}{'#pred':<7}{'maxconf':<9}{'pred confs'}")
    print("-" * 60)

    cur = 0
    while annotated and cur <= annotated[-1]:
        ret, frame = cap.read()
        if not ret:
            break
        if cur in gt:
            n_annotated_scanned += 1
            res = model.predict(frame, imgsz=args.imgsz, conf=args.conf,
                                verbose=False)[0]
            confs = (res.boxes.conf.cpu().numpy()
                     if res.boxes is not None and len(res.boxes) else np.array([]))
            xywh = (res.boxes.xywh.cpu().numpy()
                    if res.boxes is not None and len(res.boxes) else np.zeros((0, 4)))
            total_preds += len(confs)
            if len(confs):
                frames_with_any_pred += 1
                max_conf_overall = max(max_conf_overall, float(confs.max()))

            if cur in sample_set:
                mc = f"{confs.max():.2f}" if len(confs) else "-"
                cs = ", ".join(f"{c:.2f}" for c in confs[:6]) if len(confs) else "(none)"
                print(f"{cur:<8}{len(gt[cur]):<6}{len(confs):<7}{mc:<9}{cs}")

                vis = frame.copy()
                # GT boxes (green)
                for b in gt[cur]:
                    x1, y1 = int(b.cx - b.width / 2), int(b.cy - b.height / 2)
                    x2, y2 = int(b.cx + b.width / 2), int(b.cy + b.height / 2)
                    cv2.rectangle(vis, (x1, y1), (x2, y2), GREEN, 2)
                # YOLO preds (red) + conf
                for (cx, cy, w, h), c in zip(xywh, confs):
                    x1, y1 = int(cx - w / 2), int(cy - h / 2)
                    x2, y2 = int(cx + w / 2), int(cy + h / 2)
                    cv2.rectangle(vis, (x1, y1), (x2, y2), RED, 2)
                    cv2.putText(vis, f"{c:.2f}", (x1, max(0, y1 - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, RED, 1)

                cv2.imwrite(str(out / f"frame_{cur:05d}_full.png"), vis)

                # 2x zoom crop around first GT head
                b0 = gt[cur][0]
                pad = 120
                cx0, cy0 = int(b0.cx), int(b0.cy)
                H, W = vis.shape[:2]
                x1 = max(0, cx0 - pad); y1 = max(0, cy0 - pad)
                x2 = min(W, cx0 + pad); y2 = min(H, cy0 + pad)
                crop = vis[y1:y2, x1:x2]
                if crop.size:
                    crop = cv2.resize(crop, None, fx=2.0, fy=2.0,
                                      interpolation=cv2.INTER_NEAREST)
                    cv2.imwrite(str(out / f"frame_{cur:05d}_zoom.png"), crop)
        cur += 1

    cap.release()

    print("-" * 60)
    print(f"Annotated frames scanned : {n_annotated_scanned}")
    print(f"Frames with >=1 pred     : {frames_with_any_pred}")
    print(f"Total predictions        : {total_preds}")
    print(f"Max confidence anywhere  : {max_conf_overall:.3f}")
    print(f"Overlays saved to        : {out}/")


if __name__ == "__main__":
    main()
