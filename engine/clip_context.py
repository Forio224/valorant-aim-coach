"""Stage 0: clip data model — player/clip identity, FPS, screen geometry.

`ClipContext` is the single container every later stage (episodes, metrics,
profile, evidence) receives alongside frame samples. FPS is read from the mp4
container in BOTH source modes:

  - video/yolo mode: straight from the clip being analysed;
  - gt mode: from the mp4 paired with the CVAT XML (the XML itself carries no
    fps, but `frame_filter step=1` + `<size>` == video frame count guarantee a
    1:1 frame-index mapping, which we validate here). A manual fps override is
    only a fallback for when the paired mp4 is unavailable.

VFR note: CAP_PROP_FPS is the container-average frame rate. That is fine for
this engine — all metric logic is ordinal (frame-order based); fps is used only
to convert second-based thresholds into frames and to render evidence
timestamps.
"""

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# Container frame counts are metadata-derived and may disagree with the CVAT
# task size by a frame or two on some codecs; anything larger means the XML is
# paired with the wrong video.
FRAME_COUNT_TOLERANCE = 2


# ── Data contracts ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VideoMeta:
    """Container-level properties of a clip (no frames decoded)."""
    fps: float
    frame_count: int
    width: int
    height: int


@dataclass(frozen=True)
class CvatMeta:
    """The slice of CVAT task metadata Stage 0 cares about."""
    frame_count: int    # <size>
    step: int           # from <frame_filter> "step=N"; 1 when absent/empty
    width: int          # <original_size>
    height: int


@dataclass(frozen=True)
class ClipContext:
    """Identity + temporal/geometric metadata of one analysed clip.

    `sens`/`edpi`/`agent`/`map_name`/`training_platform` are user-supplied
    input-space facts the video cannot see; they are carried verbatim into
    reports, never inferred.
    """
    player_id: str
    clip_id: str
    fps: float
    width: int
    height: int
    frame_count: int
    sens: Optional[float] = None
    edpi: Optional[float] = None
    agent: Optional[str] = None
    map_name: Optional[str] = None
    training_platform: Optional[str] = None   # "kovaaks" | "ingame" | None

    def __post_init__(self) -> None:
        if not self.player_id:
            raise ValueError("player_id must be a non-empty string")
        if not self.clip_id:
            raise ValueError("clip_id must be a non-empty string")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError(f"fps must be a positive finite number, got {self.fps!r}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"resolution must be positive, got {self.width}x{self.height}")
        if self.frame_count <= 0:
            raise ValueError(f"frame_count must be positive, got {self.frame_count}")
        if self.training_platform not in (None, "kovaaks", "ingame"):
            raise ValueError(
                f"training_platform must be 'kovaaks' | 'ingame' | None, "
                f"got {self.training_platform!r}")

    @property
    def crosshair(self) -> Tuple[float, float]:
        """Valorant locks the crosshair to the screen centre."""
        return self.width / 2.0, self.height / 2.0

    def frame_to_seconds(self, frame_idx: int) -> float:
        return frame_idx / self.fps


# ── Metadata readers ─────────────────────────────────────────────────────────

def read_video_meta(video_path: str) -> VideoMeta:
    """Container properties via cv2 — open/get/release, no frame decode."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {video_path}")
    try:
        return VideoMeta(
            fps=float(cap.get(cv2.CAP_PROP_FPS)),
            frame_count=int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT))),
            width=int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))),
            height=int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))),
        )
    finally:
        cap.release()


def parse_cvat_meta(xml_path: str) -> CvatMeta:
    """Task metadata from a CVAT video-annotation XML (meta/task block)."""
    task = ET.parse(xml_path).getroot().find("meta/task")
    if task is None:
        raise ValueError(f"no <meta><task> block in CVAT XML: {xml_path}")

    size_el = task.find("size")
    orig = task.find("original_size")
    if size_el is None or orig is None:
        raise ValueError(f"CVAT XML lacks <size>/<original_size>: {xml_path}")

    filter_el = task.find("frame_filter")
    filter_text = (filter_el.text or "").strip() if filter_el is not None else ""
    step = int(filter_text.split("=", 1)[1]) if filter_text.startswith("step=") else 1

    return CvatMeta(
        frame_count=int(size_el.text),
        step=step,
        width=int(orig.find("width").text),
        height=int(orig.find("height").text),
    )


# ── Context builders (one per frame source) ──────────────────────────────────

def _resolve_fps(video_fps: Optional[float], fps_override: Optional[float],
                 origin: str) -> float:
    """Prefer container fps; fall back to the manual override; else fail fast."""
    if video_fps is not None and math.isfinite(video_fps) and video_fps > 0:
        return video_fps
    if fps_override is not None:
        return fps_override
    raise ValueError(
        f"no usable fps for {origin}: container gave {video_fps!r} and no "
        f"--fps override was provided"
    )


def context_for_video(video_path: str, *, player_id: str,
                      clip_id: Optional[str] = None,
                      fps_override: Optional[float] = None,
                      sens: Optional[float] = None,
                      edpi: Optional[float] = None,
                      agent: Optional[str] = None,
                      map_name: Optional[str] = None,
                      training_platform: Optional[str] = None) -> ClipContext:
    """ClipContext for the yolo/video source: everything from the container."""
    meta = read_video_meta(video_path)
    return ClipContext(
        player_id=player_id,
        clip_id=clip_id or Path(video_path).stem,
        fps=_resolve_fps(meta.fps, fps_override, video_path),
        width=meta.width,
        height=meta.height,
        frame_count=meta.frame_count,
        sens=sens, edpi=edpi, agent=agent, map_name=map_name,
        training_platform=training_platform,
    )


def context_for_gt(xml_path: str, video_path: Optional[str] = None,
                   fps_override: Optional[float] = None, *, player_id: str,
                   clip_id: Optional[str] = None,
                   sens: Optional[float] = None,
                   edpi: Optional[float] = None,
                   agent: Optional[str] = None,
                   map_name: Optional[str] = None,
                   training_platform: Optional[str] = None) -> ClipContext:
    """ClipContext for the gt source: geometry from XML, fps from paired mp4.

    Validates the 1:1 frame-index mapping the rest of the engine relies on:
    frame_filter must be step=1 and the paired video's frame count must match
    the CVAT task size (within FRAME_COUNT_TOLERANCE).
    """
    meta = parse_cvat_meta(xml_path)
    if meta.step != 1:
        raise ValueError(
            f"CVAT frame_filter step={meta.step} is not supported: frame "
            f"indices would not map 1:1 onto video frames ({xml_path})"
        )

    video_fps: Optional[float] = None
    if video_path is not None:
        vmeta = read_video_meta(video_path)
        if abs(vmeta.frame_count - meta.frame_count) > FRAME_COUNT_TOLERANCE:
            raise ValueError(
                f"frame count mismatch: XML task size={meta.frame_count} but "
                f"video has {vmeta.frame_count} frames — is {video_path} "
                f"really the clip behind {xml_path}?"
            )
        video_fps = vmeta.fps

    return ClipContext(
        player_id=player_id,
        clip_id=clip_id or Path(xml_path).stem,
        fps=_resolve_fps(video_fps, fps_override, xml_path),
        width=meta.width,
        height=meta.height,
        frame_count=meta.frame_count,
        sens=sens, edpi=edpi, agent=agent, map_name=map_name,
        training_platform=training_platform,
    )
