import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

root_path = Path(__file__).resolve().parent.parent
sys.path.append(str(root_path))

import cv2
import numpy as np

try:
    from backend.centroid_head_detector import CentroidHeadDetector, HSV_PRESETS, FrameResult
except ModuleNotFoundError:
    try:
        from centroid_head_detector import CentroidHeadDetector, HSV_PRESETS, FrameResult
    except ImportError:
        print("Error: Could not find centroid_head_detector.py.")
        sys.exit(1)


SENSING_CONFIG = {
    "enemy_highlight_color": "red",
    "decision_boundary_hu": 0.5,
    "target_mae": 0.125,
    "min_confidence": 0.25,
    # Skip occluded annotations (head heavily obscured by geometry)
    "skip_occluded": True,
}

# Fractions of frame dimensions defining HUD zones excluded from MAE evaluation.
# Ground-truth annotations whose head center falls inside any zone are skipped
# (same treatment as FLASH frames — excluded, not penalized).
HUD_ZONES = {
    # Top-left: streamer webcam/face-cam overlay.
    # Matches detector overlay_topleft_frac=(0.22, 0.30).
    "webcam": {"x_max": 0.22, "y_max": 0.30},
    # Bottom strip: ability bar + health. Matches detector ui_bottom_frac=0.20.
    "abilities": {"y_min": 0.80},
    # Bottom-right: agent splash art overlay.
    # Matches detector overlay_botright_frac=(0.88, 0.68).
    "splash": {"x_min": 0.88, "y_min": 0.68},
}


@dataclass
class FrameTruth:
    frame_id: int
    head_center: Tuple[float, float]
    crosshair_pos: Tuple[float, float]
    head_height: float


@dataclass
class ClipStats:
    """Detailed per-clip evaluation breakdown."""
    hits: int = 0          # frames: detector fired + confidence OK
    misses: int = 0        # frames: no detection or low confidence (penalized)
    flash_skip: int = 0    # frames: FLASH quality — excluded from MAE
    hud_skip: int = 0      # frames: ground-truth head inside HUD zone — excluded from MAE
    hit_errors: List[float] = field(default_factory=list)

    @property
    def total_evaluated(self) -> int:
        return self.hits + self.misses

    @property
    def detection_rate(self) -> float:
        return self.hits / self.total_evaluated if self.total_evaluated > 0 else 0.0

    @property
    def hit_mae(self) -> float:
        """MAE over frames where a detection was actually made."""
        return float(np.mean(self.hit_errors)) if self.hit_errors else float("nan")

    @property
    def overall_mae(self) -> float:
        """MAE including 1.0 HU penalty for each miss."""
        all_errors = self.hit_errors + [1.0] * self.misses
        return float(np.mean(all_errors)) if all_errors else float("nan")


class CVATParser:
    """
    Parses CVAT XML track-based exports.

    Fix vs v1: filters outside="1" frames — these carry interpolated coordinates
    for frames where the object has left the scene. Feeding them as ground truth
    forces a 1.0 HU penalty every time (detector correctly finds nothing), which
    was the primary driver of inflated MAE.
    """

    def __init__(self, skip_occluded: bool = True):
        self.skip_occluded = skip_occluded

    def parse_xml(self, xml_path: str) -> Dict[int, FrameTruth]:
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception as e:
            print(f"  [Parser] Error reading {xml_path}: {e}")
            return {}

        heads: Dict[int, dict] = {}
        crosshairs: Dict[int, Tuple[float, float]] = {}
        outside_skipped = 0
        occluded_skipped = 0

        for track in root.findall("track"):
            label = track.get("label")

            if label == "head":
                for box in track.findall("box"):
                    if box.get("outside", "0") == "1":
                        outside_skipped += 1
                        continue
                    if self.skip_occluded and box.get("occluded", "0") == "1":
                        occluded_skipped += 1
                        continue
                    try:
                        f_id = int(box.get("frame"))
                        xtl = float(box.get("xtl"))
                        ytl = float(box.get("ytl"))
                        xbr = float(box.get("xbr"))
                        ybr = float(box.get("ybr"))
                        heads[f_id] = {
                            "center": ((xtl + xbr) / 2.0, (ytl + ybr) / 2.0),
                            "height": ybr - ytl,
                        }
                    except (ValueError, TypeError):
                        continue

            elif label == "crosshair":
                for pt in track.findall("points"):
                    if pt.get("outside", "0") == "1":
                        outside_skipped += 1
                        continue
                    try:
                        f_id = int(pt.get("frame"))
                        coords = pt.get("points").split(",")
                        crosshairs[f_id] = (float(coords[0]), float(coords[1]))
                    except (ValueError, TypeError, IndexError):
                        continue

        if outside_skipped:
            print(f"  [Parser] Skipped {outside_skipped} outside-frame annotations")
        if occluded_skipped:
            print(f"  [Parser] Skipped {occluded_skipped} occluded-frame annotations")

        # Crosshair in Valorant is always (w/2, h/2) — no annotation needed.
        # Fall back to (0, 0) placeholder; evaluation only uses head_center + head_height.
        truth: Dict[int, FrameTruth] = {}
        for f_id, head in heads.items():
            crosshair = crosshairs.get(f_id, (0.0, 0.0))
            truth[f_id] = FrameTruth(
                frame_id=f_id,
                head_center=head["center"],
                crosshair_pos=crosshair,
                head_height=head["height"],
            )
        return truth


class SensingSpikeRunner:
    def __init__(self):
        self.detector = CentroidHeadDetector(
            HSV_PRESETS[SENSING_CONFIG["enemy_highlight_color"]]
        )
        self._parser = CVATParser(skip_occluded=SENSING_CONFIG["skip_occluded"])

    @staticmethod
    def _in_hud_zone(x: float, y: float, frame_w: int, frame_h: int) -> str | None:
        """
        Return the zone name if (x, y) falls inside a HUD exclusion region,
        or None if the point is in the playfield.

        Zones are defined as fractions of frame dimensions in HUD_ZONES.
        """
        rx, ry = x / frame_w, y / frame_h
        for zone_name, bounds in HUD_ZONES.items():
            if (rx <= bounds.get("x_max", 1.0)
                    and rx >= bounds.get("x_min", 0.0)
                    and ry <= bounds.get("y_max", 1.0)
                    and ry >= bounds.get("y_min", 0.0)):
                return zone_name
        return None

    def run_spike(self, video_path: str, truth_data: Dict[int, FrameTruth]) -> ClipStats:
        cap = cv2.VideoCapture(video_path)
        stats = ClipStats()
        frame_idx = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx in truth_data:
                truth = truth_data[frame_idx]
                frame_h, frame_w = frame.shape[:2]

                # Skip frames where the annotated head is inside a HUD region.
                # The detector masks these zones, so forcing a miss/hit there
                # would measure UI-occlusion rather than detector quality.
                hx, hy = truth.head_center
                if self._in_hud_zone(hx, hy, frame_w, frame_h):
                    stats.hud_skip += 1
                    frame_idx += 1
                    continue

                result = self.detector.detect(frame)

                if result.frame_quality == "FLASH":
                    # Flash blinds the frame entirely — physically undetectable.
                    # Excluded from MAE rather than penalized (would inflate the
                    # metric independently of actual detector quality).
                    stats.flash_skip += 1

                elif result.best and result.best.confidence >= SENSING_CONFIG["min_confidence"]:
                    det = result.best
                    dist_px = np.sqrt(
                        (det.center_x - hx) ** 2
                        + (det.center_y - hy) ** 2
                    )
                    error_hu = dist_px / max(truth.head_height, 1.0)
                    stats.hits += 1
                    stats.hit_errors.append(error_hu)

                else:
                    # Genuine miss: no detection or confidence below threshold.
                    # Penalized with 1.0 HU so low detection-rate hurts overall MAE.
                    stats.misses += 1

            frame_idx += 1

        cap.release()
        return stats


def _fmt(value: float, decimals: int = 4) -> str:
    return f"{value:.{decimals}f}" if not np.isnan(value) else "N/A"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, required=True, help="Path to dataset folder")
    args = parser.parse_args()

    runner = SensingSpikeRunner()
    dataset_path = Path(args.dataset)

    global_stats = ClipStats()

    for category in ["control", "target", "adversarial"]:
        cat_path = dataset_path / category
        if not cat_path.exists():
            continue

        print(f"\n{'='*40}")
        print(f"Category: {category.upper()}")
        print(f"{'='*40}")

        for video_file in sorted(cat_path.glob("*.mp4")):
            xml_file = video_file.with_suffix(".xml")
            if not xml_file.exists():
                print(f"  {video_file.name} — no XML, skipped")
                continue

            truth = runner._parser.parse_xml(str(xml_file))
            if not truth:
                print(f"  {video_file.name} — no valid annotations, skipped")
                continue

            clip = runner.run_spike(str(video_file), truth)

            global_stats.hits += clip.hits
            global_stats.misses += clip.misses
            global_stats.flash_skip += clip.flash_skip
            global_stats.hud_skip += clip.hud_skip
            global_stats.hit_errors.extend(clip.hit_errors)

            det_pct = clip.detection_rate * 100
            print(
                f"  {video_file.name}"
                f"  evaluated={clip.total_evaluated}"
                f"  hits={clip.hits} ({det_pct:.0f}%)"
                f"  misses={clip.misses}"
                f"  flash_skip={clip.flash_skip}"
                f"  hud_skip={clip.hud_skip}"
                f"  hit_MAE={_fmt(clip.hit_mae)}"
                f"  overall_MAE={_fmt(clip.overall_mae)}"
            )

    print(f"\n{'='*40}")
    print("FINAL SPIKE RESULT")
    print(f"{'='*40}")
    total_eval = global_stats.total_evaluated
    if total_eval == 0:
        print("No valid data processed. Check XML files and video paths.")
        sys.exit(1)

    det_pct = global_stats.detection_rate * 100
    target = SENSING_CONFIG["target_mae"]
    overall = global_stats.overall_mae

    print(f"Frames evaluated : {total_eval}")
    print(f"  Hits           : {global_stats.hits} ({det_pct:.1f}%)")
    print(f"  Misses         : {global_stats.misses}")
    print(f"  Flash-skipped  : {global_stats.flash_skip}")
    print(f"  HUD-skipped    : {global_stats.hud_skip}  (minimap / weapon / abilities)")
    print(f"Hit MAE          : {_fmt(global_stats.hit_mae)} HU  (precision when detector fires)")
    print(f"Overall MAE      : {_fmt(overall)} HU  (includes 1.0 penalty per miss)")
    print(f"Target MAE       : {target} HU")
    print(f"Verdict          : {'PASS' if overall <= target else 'FAIL'}")
