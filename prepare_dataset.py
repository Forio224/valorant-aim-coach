r"""
prepare_dataset.py
===================
Convert MULTIPLE CVAT XML annotations + source videos into one YOLO detection
dataset (multi-clip).

Output layout (Ultralytics YOLO format):
    dataset/
      images/train/<clip>_00074.png
      images/val/<clip>_00123.png
      images/test/<clip>_00254.png
      labels/train/<clip>_00074.txt   # "0 cx cy w h"  (normalised 0..1)
      labels/val/...
      labels/test/...

Two split levels:
  - train/val come from the TRAINVAL_CLIPS pool. Each clip is split TEMPORALLY
    (last val_frac of its own timeline → val), so every map/colour appears in
    both train and val for fit monitoring.
  - test is a WHOLE held-out clip (HOLDOUT_TEST) the model never trains on —
    the honest cross-clip / colour-invariance probe (also runnable via
    yolo_mae.py on the raw clip).

Frame indices collide across clips (clip A frame 74 and clip B frame 74), so
every image/label is prefixed with a per-clip slug to keep them distinct.

Each clip is normalised by ITS OWN original_size (resolutions differ:
output_clip is 2560x1440, the rest 1920x1080).

Usage:
    .\.venv\Scripts\python.exe prepare_dataset.py
    .\.venv\Scripts\python.exe prepare_dataset.py --val-frac 0.2
"""

import argparse
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import cv2


# frame_index -> list of (cx, cy, w, h) in PIXELS
FrameBoxes = Dict[int, List[Tuple[float, float, float, float]]]


# ── Clip manifest ────────────────────────────────────────────────────────────────
# (video, xml) pairs. Edit here to add/remove clips.

TRAINVAL_CLIPS: List[Tuple[str, str]] = [
    ("dataset1/output_clip.mp4",            "dataset1/output_clip.xml"),            # yellow, 2560x1440
    ("dataset1/clip2.mp4",                  "dataset1/clip2.xml"),                  # red, reworked flick+micro (1920x1080)
    ("dataset1/clip3.mp4",                  "dataset1/clip3.xml"),                  # red, new clip (1920x1080)
    ("dataset/Control/2k.mp4",              "dataset/Control/2k.xml"),              # red
    ("dataset/Control/2k_1.mp4",            "dataset/Control/2k_1.xml"),            # red
    ("dataset/Adversarial/1k(smoke).mp4",   "dataset/Adversarial/1k(smoke).xml"),   # red + smoke
    ("dataset/Adversarial/2k(flash).mp4",   "dataset/Adversarial/2k(flash).xml"),   # red + flash
]

# Whole clip held out as the honest colour-invariance test (never trained on).
HOLDOUT_TEST: List[Tuple[str, str]] = [
    ("dataset/Control/2k_2.mp4",            "dataset/Control/2k_2.xml"),            # red, verified-good GT
]


def clip_slug(video_path: str) -> str:
    """Stable per-clip prefix, e.g. dataset/Control/1k(smoke).mp4 -> control_1k_smoke."""
    p = Path(video_path)
    parent = p.parent.name                       # Control / Adversarial / dataset1
    stem = f"{parent}_{p.stem}"
    return re.sub(r"[^0-9a-zA-Z]+", "_", stem).strip("_").lower()


def parse_cvat_xml(xml_path: str) -> Tuple[FrameBoxes, int, int]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    size_el = root.find(".//original_size")
    width = int(size_el.find("width").text)
    height = int(size_el.find("height").text)

    boxes: FrameBoxes = defaultdict(list)
    for track in root.findall("track"):
        for box in track.findall("box"):
            if box.attrib.get("outside", "0") == "1":
                continue
            frame = int(box.attrib["frame"])
            xtl = float(box.attrib["xtl"])
            ytl = float(box.attrib["ytl"])
            xbr = float(box.attrib["xbr"])
            ybr = float(box.attrib["ybr"])
            boxes[frame].append((
                (xtl + xbr) / 2.0, (ytl + ybr) / 2.0, xbr - xtl, ybr - ytl,
            ))

    return boxes, width, height


def temporal_split(frames: List[int], val_frac: float) -> Tuple[set, set]:
    """Hold out the LAST val_frac of the timeline as validation."""
    frames_sorted = sorted(frames)
    n_val = max(1, int(len(frames_sorted) * val_frac))
    val = set(frames_sorted[-n_val:])
    train = set(frames_sorted[:-n_val])
    return train, val


def write_label(label_path: Path, boxes: List[Tuple[float, float, float, float]],
                img_w: int, img_h: int) -> None:
    lines = [f"0 {cx/img_w:.6f} {cy/img_h:.6f} {w/img_w:.6f} {h/img_h:.6f}"
             for cx, cy, w, h in boxes]
    label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fresh_dirs(out: Path) -> None:
    """Recreate only the YOLO split dirs; leave source clip folders untouched."""
    for split in ("train", "val", "test"):
        for kind in ("images", "labels"):
            d = out / kind / split
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)


def export_clip(video: str, xml: str, out: Path,
                frame_to_split: Dict[int, str]) -> Tuple[int, int]:
    """Decode a clip sequentially and write images/labels per the split map.
    Returns (frames_written, boxes_written)."""
    slug = clip_slug(video)
    boxes, img_w, img_h = parse_cvat_xml(xml)
    wanted = set(boxes.keys())
    if not wanted:
        print(f"  WARN {slug}: no annotated frames, skipped")
        return 0, 0

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        print(f"  ERROR cannot open video: {video}")
        sys.exit(1)

    # Sequential decode guarantees image[frame_idx] matches label[frame_idx];
    # cap.set(POS_FRAMES) can be off-by-one on some H.264 builds.
    written = 0
    boxes_written = 0
    cur = 0
    remaining = set(wanted)
    while remaining:
        ret, frame = cap.read()
        if not ret:
            break
        if cur in wanted:
            split = frame_to_split[cur]
            stem = f"{slug}_{cur:05d}"
            cv2.imwrite(str(out / "images" / split / f"{stem}.png"), frame)
            write_label(out / "labels" / split / f"{stem}.txt",
                        boxes[cur], img_w, img_h)
            written += 1
            boxes_written += len(boxes[cur])
            remaining.discard(cur)
        cur += 1
    cap.release()

    n_val = sum(1 for f in wanted if frame_to_split[f] == "val")
    n_test = sum(1 for f in wanted if frame_to_split[f] == "test")
    n_train = written - n_val - n_test
    print(f"  {slug:<26} {img_w}x{img_h:<6} "
          f"train={n_train:<4} val={n_val:<4} test={n_test:<4} boxes={boxes_written}")
    return written, boxes_written


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-clip CVAT XML -> YOLO dataset")
    parser.add_argument("--out",      default="dataset")
    parser.add_argument("--val-frac", type=float, default=0.2)
    args = parser.parse_args()

    out = Path(args.out)
    fresh_dirs(out)

    total_imgs = 0
    total_boxes = 0

    print("TRAIN/VAL pool (per-clip temporal split):")
    for video, xml in TRAINVAL_CLIPS:
        boxes, _, _ = parse_cvat_xml(xml)
        frames = sorted(boxes.keys())
        train_f, val_f = temporal_split(frames, args.val_frac)
        f2s = {f: ("val" if f in val_f else "train") for f in frames}
        w, b = export_clip(video, xml, out, f2s)
        total_imgs += w
        total_boxes += b

    print("\nHOLDOUT test (whole clip, never trained):")
    for video, xml in HOLDOUT_TEST:
        boxes, _, _ = parse_cvat_xml(xml)
        f2s = {f: "test" for f in boxes.keys()}
        w, b = export_clip(video, xml, out, f2s)
        total_imgs += w
        total_boxes += b

    # Final tallies per split.
    def count(split: str) -> int:
        d = out / "images" / split
        return len(list(d.glob("*.png"))) if d.exists() else 0

    print("\n" + "=" * 55)
    print(f"  Dataset built at {out}/")
    print(f"  train images : {count('train')}")
    print(f"  val images   : {count('val')}")
    print(f"  test images  : {count('test')}  (holdout, not in data.yaml train/val)")
    print(f"  total images : {total_imgs}")
    print(f"  total boxes  : {total_boxes}")
    print("=" * 55)


if __name__ == "__main__":
    main()
