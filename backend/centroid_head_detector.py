"""
centroid_head_detector.py
=========================
Drop-in replacement for YOLO-based head detection in sensing_spike_runner.py.

Core idea:
  Valorant renders a solid color outline around every enemy. The outline color
  is user-configurable (enemy_highlight_color). Instead of asking YOLO "where
  is the person?", we ask OpenCV "where is the dense cluster of highlight pixels
  at the TOP of the visible outline region?" — that cluster is the head.

Valorant-specific shortcut:
  The crosshair is ALWAYS at screen center (frame_w/2, frame_h/2).
  We don't need to detect it. Placement offset is simply:
      offset = head_center - screen_center

Usage (drop-in):
  detector = CentroidHeadDetector(HSV_PRESETS["red"])
  result   = detector.detect(frame)          # single best detection
  results  = detector.detect_all(frame)      # all enemies in frame
  debug_frame = detector.draw_debug(frame)   # visualization
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict


# ──────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────

@dataclass
class HSVRange:
    """
    HSV colour range for enemy highlight.
    Red wraps around 180°, so we support two ranges merged with OR.
    """
    h_min: int; h_max: int          # primary range
    s_min: int; s_max: int
    v_min: int; v_max: int
    h_min2: Optional[int] = None    # secondary range (red wrap-around)
    h_max2: Optional[int] = None


@dataclass
class HeadDetection:
    center_x: float          # global frame coords
    center_y: float
    head_height_px: float    # estimated head bbox height (for HU normalisation)
    confidence: float        # 0.0 – 1.0
    pixel_count: int         # number of highlight pixels in head ROI
    body_bbox: Tuple[int,int,int,int] = field(default=(0,0,0,0))  # (x,y,w,h) full body


@dataclass
class FrameResult:
    detections: List[HeadDetection]
    crosshair: Tuple[float, float]          # always (w/2, h/2) in Valorant
    frame_quality: str                      # "OK" | "FLASH" | "SMOKE"
    # Best detection shortcut
    @property
    def best(self) -> Optional[HeadDetection]:
        return self.detections[0] if self.detections else None


# ──────────────────────────────────────────────
# Common HSV presets (Valorant highlight colors)
# ──────────────────────────────────────────────

HSV_PRESETS: Dict[str, HSVRange] = {
    # Settings → Crosshair → Enemy Highlight Color
    "red": HSVRange(
        h_min=165, h_max=180, s_min=140, s_max=255, v_min=80, v_max=255,
        h_min2=0,  h_max2=10           # red wraps around 0°
    ),
    "yellow": HSVRange(
        h_min=24, h_max=40, s_min=80, s_max=255, v_min=180, v_max=255
    ),
    "orange": HSVRange(
        h_min=10, h_max=22, s_min=150, s_max=255, v_min=100, v_max=255
    ),
    "white": HSVRange(
        h_min=0, h_max=180, s_min=0, s_max=40, v_min=200, v_max=255
    ),
    "green": HSVRange(
        h_min=45, h_max=85, s_min=120, s_max=255, v_min=80, v_max=255
    ),
}


# ──────────────────────────────────────────────
# Core detector
# ──────────────────────────────────────────────

class CentroidHeadDetector:
    """
    Pipeline:
      Frame → [L1 Frame Gate] → HSV Mask → Contour Detection
            → [Top-of-body ROI] → Centroid → HeadDetection
    """

    def __init__(
        self,
        hsv_range: HSVRange,
        # ── Geometry ─────────────────────────────────────────────────────────
        head_top_ratio: float = 0.22,   # top 22% of outline bbox = head region (raised for thin outlines)
        min_body_area:  int   = 80,     # px² — thin outline at 2560x1440 ≈ 100-200px², 400 was too aggressive
        min_head_pixels: int  = 10,     # minimum outline pixels in head ROI
        min_body_height: int  = 25,     # px — filter tiny far specks
        max_body_height: int  = 400,    # px — characters/heads aren't 400px+ tall
        min_body_aspect: float = 0.6,   # bh/bw >= 0.6: allows crouching/leaning enemies (was 1.0)
        # ── HUD exclusion zones (Valorant 16:9 layout) ───────────────────────
        ui_bottom_frac: float = 0.20,   # bottom 20% = ability bar + health
        ui_sides_frac:  float = 0.07,   # 7% each side = minimap / scoreboard
        ui_top_frac:    float = 0.06,   # top 6% = kill feed
        # ── Streamer overlay exclusion zones ─────────────────────────────────
        # Webcam / face-cam placed top-left by OBS/SLOBS.
        # (w_frac, h_frac) = fraction of frame the overlay occupies.
        overlay_topleft_frac: tuple = (0.22, 0.30),
        # Agent splash art placed bottom-right.
        # (x_start_frac, y_start_frac) = where the overlay begins.
        overlay_botright_frac: tuple = (0.88, 0.68),
        # ── Own model exclusion (player's hands/weapon always center-bottom) ──
        own_model_bottom_frac: float = 0.35,  # bottom 35% of center strip = player's own model
        own_model_center_frac: float = 0.30,  # center 30% of frame width
        # ── Max plausible HU offset from crosshair ────────────────────────────
        # Rejects stream overlays and other off-screen false positives
        max_hu_radius: float = 15.0,
        # ── Frame quality gates ───────────────────────────────────────────────
        flash_brightness_thresh: int = 210,
        smoke_saturation_thresh: int = 35,
        morph_kernel_size: int = 3,
    ):
        self.hsv                  = hsv_range
        self.head_top_ratio       = head_top_ratio
        self.min_body_area        = min_body_area
        self.min_head_pixels      = min_head_pixels
        self.min_body_height      = min_body_height
        self.max_body_height      = max_body_height
        self.min_body_aspect      = min_body_aspect
        self.ui_bottom_frac        = ui_bottom_frac
        self.ui_sides_frac         = ui_sides_frac
        self.ui_top_frac           = ui_top_frac
        self.overlay_topleft_frac  = overlay_topleft_frac
        self.overlay_botright_frac = overlay_botright_frac
        self.own_model_bottom_frac = own_model_bottom_frac
        self.own_model_center_frac = own_model_center_frac
        self.max_hu_radius        = max_hu_radius
        self.flash_thresh         = flash_brightness_thresh
        self.smoke_thresh         = smoke_saturation_thresh
        self._kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size)
        )

    # ── Public API ──────────────────────────────

    def detect(self, frame: np.ndarray) -> FrameResult:
        """Return FrameResult with all detections sorted by confidence."""
        h, w = frame.shape[:2]
        crosshair = (w / 2.0, h / 2.0)

        quality = self._frame_quality(frame)
        if quality == "FLASH":
            return FrameResult(detections=[], crosshair=crosshair, frame_quality="FLASH")

        mask = self._build_mask(frame)

        # ── Erase HUD / UI zones before contour detection ──────────────────
        # Valorant HUD: bottom strip (abilities/health), side strips (minimap
        # border, scoreboard), thin top strip (kill feed header).
        # This eliminates the #1 source of false positives (root cause of 28 HU).
        top_px  = int(h * self.ui_top_frac)
        bot_px  = int(h * (1.0 - self.ui_bottom_frac))
        side_px = int(w * self.ui_sides_frac)
        mask[:top_px, :]    = 0   # top strip (kill feed)
        mask[bot_px:, :]    = 0   # bottom HUD (abilities / health)
        mask[:, :side_px]   = 0   # left side (minimap border)
        mask[:, w-side_px:] = 0   # right side (scoreboard)

        # ── Streamer overlay zones ──────────────────────────────────────────
        # Webcam / face-cam (top-left): covers the full rectangle from the
        # corner inward by overlay_topleft_frac (w%, h%) of the frame.
        tl_w = int(w * self.overlay_topleft_frac[0])
        tl_h = int(h * self.overlay_topleft_frac[1])
        mask[:tl_h, :tl_w] = 0

        # Agent splash art / outro card (bottom-right): starts at
        # overlay_botright_frac (x%, y%) and extends to the corner.
        br_x = int(w * self.overlay_botright_frac[0])
        br_y = int(h * self.overlay_botright_frac[1])
        mask[br_y:, br_x:] = 0

        # Player's own model (hands/weapon) is always in the center-bottom strip.
        # Erasing this zone prevents Jett's red clothing from being detected as enemy.
        own_top  = int(h * (1.0 - self.own_model_bottom_frac))
        own_left = int(w * (0.5 - self.own_model_center_frac / 2))
        own_right = int(w * (0.5 + self.own_model_center_frac / 2))
        mask[own_top:, own_left:own_right] = 0

        detections = self._find_heads(mask, quality)

        # Reject detections whose HU offset from crosshair is physically implausible
        # (typically stream overlays, edge glitches, or camera artifacts).
        cx, cy = crosshair
        detections = [
            d for d in detections
            if (abs(d.center_x - cx) / max(d.head_height_px, 1.0) <= self.max_hu_radius
                and abs(d.center_y - cy) / max(d.head_height_px, 1.0) <= self.max_hu_radius)
        ]

        return FrameResult(detections=detections, crosshair=crosshair, frame_quality=quality)

    def draw_debug(self, frame: np.ndarray) -> np.ndarray:
        """Returns annotated frame for visual inspection."""
        result = self.detect(frame)
        out = frame.copy()

        # Draw crosshair (always screen center)
        cx, cy = int(result.crosshair[0]), int(result.crosshair[1])
        cv2.drawMarker(out, (cx, cy), (0,255,0), cv2.MARKER_CROSS, 20, 2)

        for i, det in enumerate(result.detections):
            color = (0, 255, 255) if i == 0 else (0, 180, 180)
            # Body bbox
            bx, by, bw, bh = det.body_bbox
            cv2.rectangle(out, (bx, by), (bx+bw, by+bh), color, 1)
            # Head center
            hx, hy = int(det.center_x), int(det.center_y)
            cv2.circle(out, (hx, hy), 5, (0,0,255), -1)
            # HU offset from crosshair
            offset_x_hu = (det.center_x - result.crosshair[0]) / max(det.head_height_px, 1)
            offset_y_hu = (det.center_y - result.crosshair[1]) / max(det.head_height_px, 1)
            label = f"HU ({offset_x_hu:+.2f}, {offset_y_hu:+.2f}) conf={det.confidence:.2f}"
            cv2.putText(out, label, (bx, by - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        # Frame quality overlay
        q_color = {"OK": (0,255,0), "SMOKE": (200,200,0), "FLASH": (0,0,255)}
        cv2.putText(out, f"Frame: {result.frame_quality}", (10,25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, q_color.get(result.frame_quality,(255,255,255)), 2)
        return out

    # ── Private helpers ──────────────────────────

    def _frame_quality(self, frame: np.ndarray) -> str:
        hsv_f = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mean_v = float(np.mean(hsv_f[:,:,2]))
        mean_s = float(np.mean(hsv_f[:,:,1]))
        # Flash: entire screen blown out = very bright AND desaturated simultaneously.
        # Checking brightness alone misclassifies bright white smoke as flash.
        if mean_v > self.flash_thresh and mean_s < self.smoke_thresh:
            return "FLASH"
        if mean_s < self.smoke_thresh:
            return "SMOKE"
        return "OK"

    def _build_mask(self, frame: np.ndarray) -> np.ndarray:
        hsv_f = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lo  = np.array([self.hsv.h_min,  self.hsv.s_min, self.hsv.v_min])
        hi  = np.array([self.hsv.h_max,  self.hsv.s_max, self.hsv.v_max])
        mask = cv2.inRange(hsv_f, lo, hi)

        # Red wrap-around (second range)
        if self.hsv.h_min2 is not None:
            lo2 = np.array([self.hsv.h_min2, self.hsv.s_min, self.hsv.v_min])
            hi2 = np.array([self.hsv.h_max2, self.hsv.s_max, self.hsv.v_max])
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv_f, lo2, hi2))

        # --- HUD MASKING ---
        # Zero out areas where HUD elements usually appear to prevent False Positives
        h, w = mask.shape
        # Top 4% (Kill feed)
        mask[0 : int(h * 0.04), :] = 0
        # Bottom 18% (Ability bar, health)
        mask[int(h * 0.82) : h, :] = 0
        # Left 5% (Minimap/HUD)
        mask[:, 0 : int(w * 0.05)] = 0
        # Right 5% (Minimap/HUD)
        mask[:, int(w * 0.95) : w] = 0

        # Morphological cleanup: close small gaps, remove single-pixel noise
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._kernel)
        return mask

    def _find_heads(self, mask: np.ndarray, quality: str) -> List[HeadDetection]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: List[HeadDetection] = []

        for contour in contours:
            # ── Gate 1: contour area ────────────────────────────────────────
            area = cv2.contourArea(contour)
            if area < self.min_body_area:
                continue

            bx, by, bw, bh = cv2.boundingRect(contour)

            # ── Gate 2: body height bounds ──────────────────────────────────
            # Too short = distant map geometry or noise.
            # Too tall  = merged multi-person blob or large prop.
            if not (self.min_body_height <= bh <= self.max_body_height):
                continue

            # ── Gate 3: aspect ratio — characters are taller than wide ──────
            # HUD icons, minimap blobs, and map props are typically wide or
            # square. A standing character has bh/bw > 1.0 at most distances.
            # We use 0.65 as minimum to accommodate crouching/leaning.
            if bw > 0 and (bh / bw) < self.min_body_aspect:
                continue

            # ── Head ROI: top N% of body bbox ───────────────────────────────
            head_h = max(int(bh * self.head_top_ratio), 8)
            head_roi = mask[by : by + head_h, bx : bx + bw]

            # ── Bounding box of highlight pixels within head ROI ─────────────
            # FIX vs v1: replaces fragile centroid + single-row width estimate.
            # The bbox approach is stable even for thin outlines where row-width
            # collapses to 0 and caused the 28 HU normalization explosion.
            coords = np.column_stack(np.where(head_roi > 0))
            pixel_count = len(coords)
            if pixel_count < self.min_head_pixels:
                continue

            min_r, min_c = int(coords[:, 0].min()), int(coords[:, 1].min())
            max_r, max_c = int(coords[:, 0].max()), int(coords[:, 1].max())

            h_px = float(max_r - min_r) + 1.0
            w_px = float(max_c - min_c) + 1.0

            # Head height ≈ diameter of the head circle.
            # For an outline, bbox w ≈ bbox h ≈ diameter — take max for safety.
            head_height_px = max(h_px, w_px) * 1.05
            head_height_px = max(head_height_px, 8.0)

            # Head center = geometric center of its pixel bbox (global coords)
            cx = bx + (min_c + max_c) / 2.0
            cy = by + (min_r + max_r) / 2.0

            # ── Confidence score ────────────────────────────────────────────
            density    = pixel_count / max(head_h * bw, 1)
            aspect_ok  = (bh / max(bw, 1)) > 0.9   # tall = probably a character
            smoke_pen  = 0.7 if quality == "SMOKE" else 1.0
            confidence = min(density * (1.0 if aspect_ok else 0.75) * smoke_pen, 1.0)

            detections.append(HeadDetection(
                center_x=cx,
                center_y=cy,
                head_height_px=head_height_px,
                confidence=confidence,
                pixel_count=pixel_count,
                body_bbox=(bx, by, bw, bh),
            ))

        detections.sort(key=lambda d: d.confidence, reverse=True)
        return detections


# ──────────────────────────────────────────────
# HU offset calculator (stateless utility)
# ──────────────────────────────────────────────

def compute_offset_hu(
    detection: HeadDetection,
    frame_w: int,
    frame_h: int,
    true_head_center: Optional[Tuple[float,float]] = None,
) -> Dict[str, float]:
    """
    Compute placement offset in Head Units.

    If true_head_center provided → returns error vs ground truth (for spike eval).
    Otherwise           → returns crosshair offset (for live pipeline).

    Returns dict with keys:
        offset_x_hu, offset_y_hu   — vs crosshair (live metric)
        error_hu                   — scalar error vs ground truth (spike metric)
    """
    cx, cy = frame_w / 2.0, frame_h / 2.0  # Valorant crosshair = screen center
    hu = max(detection.head_height_px, 1.0)

    offset_x_hu = (detection.center_x - cx) / hu
    offset_y_hu = (detection.center_y - cy) / hu   # negative = above crosshair

    result = {"offset_x_hu": offset_x_hu, "offset_y_hu": offset_y_hu}

    if true_head_center is not None:
        tx, ty = true_head_center
        error_hu = np.sqrt(
            ((detection.center_x - tx) / hu) ** 2 +
            ((detection.center_y - ty) / hu) ** 2
        )
        result["error_hu"] = error_hu

    return result


# ──────────────────────────────────────────────
# Quick calibration helper
# ──────────────────────────────────────────────

def tune_hsv_interactive(image_path: str) -> None:
    """
    Opens a trackbar window to find the right HSV range for your setup.
    Press 'q' to quit, 's' to print current values.

    Usage: tune_hsv_interactive("path/to/valorant_screenshot.png")
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {image_path}")

    win = "HSV Tuner - press S to print, Q to quit"
    cv2.namedWindow(win)
    for name, val in [("H_min",0),("H_max",20),("S_min",140),("S_max",255),
                      ("V_min",80),("V_max",255)]:
        cv2.createTrackbar(name, win, val, 255 if "S" in name or "V" in name else 180, lambda x: None)

    while True:
        vals = {n: cv2.getTrackbarPos(n, win)
                for n in ["H_min","H_max","S_min","S_max","V_min","V_max"]}
        hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv_img,
                           np.array([vals["H_min"], vals["S_min"], vals["V_min"]]),
                           np.array([vals["H_max"], vals["S_max"], vals["V_max"]]))
        preview = cv2.bitwise_and(img, img, mask=mask)
        cv2.imshow(win, np.hstack([img, preview]))
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('s'):
            print(f"\nHSVRange(h_min={vals['H_min']}, h_max={vals['H_max']}, "
                  f"s_min={vals['S_min']}, s_max={vals['S_max']}, "
                  f"v_min={vals['V_min']}, v_max={vals['V_max']})")
    cv2.destroyAllWindows()


# ──────────────────────────────────────────────
# Integration snippet for sensing_spike_runner.py
# ──────────────────────────────────────────────
#
# Replace your YOLO block with this:
#
#   from centroid_head_detector import CentroidHeadDetector, HSV_PRESETS, compute_offset_hu
#
#   detector = CentroidHeadDetector(HSV_PRESETS["red"])   # change preset as needed
#
#   # In process_frame():
#   frame_result = detector.detect(frame)
#   det = frame_result.best
#   if det is None or frame_result.frame_quality == "FLASH":
#       all_errors.append(1.0)   # same penalty as before
#       continue
#
#   metrics = compute_offset_hu(det, frame.shape[1], frame.shape[0],
#                               true_head_center=(true_x, true_y))
#   all_errors.append(metrics["error_hu"])
#
# ──────────────────────────────────────────────


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python centroid_head_detector.py <video.mp4> [color_preset]")
        print(f"Presets: {list(HSV_PRESETS.keys())}")
        sys.exit(1)

    video_path  = sys.argv[1]
    preset_name = sys.argv[2] if len(sys.argv) > 2 else "red"
    detector    = CentroidHeadDetector(HSV_PRESETS[preset_name])

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Cannot open: {video_path}")
        sys.exit(1)

    print(f"Running debug visualisation on {video_path} (preset={preset_name})")
    print("Press SPACE to pause, Q to quit, D to toggle debug overlay")
    debug = True

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        display = detector.draw_debug(frame) if debug else frame
        cv2.imshow("Centroid Detector Debug", display)
        key = cv2.waitKey(30) & 0xFF
        if key == ord('q'):
            break
        if key == ord('d'):
            debug = not debug
        if key == ord(' '):
            cv2.waitKey(0)

    cap.release()
    cv2.destroyAllWindows()
