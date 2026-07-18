"""Stage 1: episode layer — the SUBSTRATE every metric stage builds on.

An episode is the track of ONE enemy head from its first visible frame (track
birth) to its disappearance. Per the amended roadmap, "near the crosshair" is a
TAG inside the track (duel_frames), never the episode boundary — otherwise
Stage 2 would measure pre-aim on a frame where the head is already near the
crosshair by construction, flattering the player.

Two ways to obtain tracks:
  - gt source: CVAT XML carries REAL track identity (<track id=...>) — use it
    directly, no heuristics (`gt_tracks` / `episodes_for_gt`);
  - yolo source: detections have no identity, so `segment_episodes` runs a
    greedy nearest-neighbour associator with a displacement gate.

All temporal thresholds are defined in SECONDS and converted to frames via
ctx.fps, so 60 fps and 30 fps clips remain comparable (differential test).
"""

import math
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from engine.geometry import DEFAULT_DUEL_HU, FrameSample, Head, sample_frame
from engine.clip_context import ClipContext

# ── Tunables (seconds-based where temporal) ──────────────────────────────────

DEFAULT_GAP_TOLERANCE_S = 0.25      # detection gaps shorter than this are bridged
DEFAULT_MIN_EPISODE_S = 0.10        # shorter runs are detector noise, dropped
DEFAULT_MAX_ASSOC_SPEED_HU_S = 900.0  # association gate: max head travel speed
MIN_ASSOC_GATE_PX = 40.0            # gate floor for tiny heads (px per frame)

# Distance buckets via head height as a range proxy, relative to screen height
# so resolutions stay comparable.
CLOSE_MIN_HEIGHT_RATIO = 0.025      # >= ~27 px at 1080p
FAR_MAX_HEIGHT_RATIO = 0.012        # <  ~13 px at 1080p

TrackPoint = Tuple[int, Head]                  # (frame_idx, head)
HeadsByFrame = Mapping[int, Sequence[Head]]


@dataclass(frozen=True)
class Episode:
    """One enemy-head track turned into a tagged, frame-anchored episode."""
    track_id: int
    start_frame: int               # track birth — Stage 2 measures placement here
    end_frame: int
    samples: Tuple[FrameSample, ...]   # HU offsets of THIS head, frame-anchored
    kind: str                      # "hold" | "flick" | "unengaged"
    distance_bucket: str           # "close" | "mid" | "far"
    multi_enemy: bool              # another head visible during the episode
    multi_from_frame: Optional[int]  # first frame with >=2 heads; None if never
    duel_frames: int               # frames with radial <= duel_hu (the TAG)
    peak_closing_speed_hu_s: float  # fastest approach toward the crosshair


# Гейт плотности детекций (Фаза 4): доля кадров эпизода, где голова реально
# детектирована. Разреженный флик-трек «слишком дырявый» для фаз-метрик И для
# перелёта — гейт применяют оба потребителя.
MIN_FLICK_DETECTION_DENSITY = 0.7   # некалибр.: грубее — вердикты по дыркам


def detection_density(ep: Episode) -> float:
    """Доля кадров эпизода с детекцией головы (1.0 = трек без дырок)."""
    return len(ep.samples) / (ep.end_frame - ep.start_frame + 1)


# ── Association (yolo path: detections carry no identity) ────────────────────

def associate_tracks(heads_by_frame: HeadsByFrame, ctx: ClipContext,
                     max_speed_hu_s: float = DEFAULT_MAX_ASSOC_SPEED_HU_S,
                     gap_tolerance_s: float = DEFAULT_GAP_TOLERANCE_S,
                     ) -> List[List[TrackPoint]]:
    """Greedy nearest-neighbour tracker with a displacement gate.

    The gate scales with head size (HU/s budget) and with the number of frames
    elapsed, so re-acquiring a head after a short detection gap stays possible.
    """
    gap_frames = max(int(round(gap_tolerance_s * ctx.fps)), 1)
    tracks: List[List[TrackPoint]] = []
    open_tracks: List[int] = []

    for frame_idx in sorted(heads_by_frame):
        heads = list(heads_by_frame[frame_idx])
        open_tracks = [t for t in open_tracks
                       if frame_idx - tracks[t][-1][0] <= gap_frames]

        candidates: List[Tuple[float, int, int]] = []
        for t in open_tracks:
            last_frame, last_head = tracks[t][-1]
            elapsed = frame_idx - last_frame
            gate = elapsed * max(max_speed_hu_s / ctx.fps * last_head.height_px,
                                 MIN_ASSOC_GATE_PX)
            for h_idx, head in enumerate(heads):
                dist = math.hypot(head.cx - last_head.cx, head.cy - last_head.cy)
                if dist <= gate:
                    candidates.append((dist, t, h_idx))

        candidates.sort(key=lambda c: c[0])
        used_tracks, used_heads = set(), set()
        for dist, t, h_idx in candidates:
            if t in used_tracks or h_idx in used_heads:
                continue
            tracks[t].append((frame_idx, heads[h_idx]))
            used_tracks.add(t)
            used_heads.add(h_idx)

        for h_idx, head in enumerate(heads):
            if h_idx not in used_heads:
                tracks.append([(frame_idx, head)])
                open_tracks.append(len(tracks) - 1)
    return tracks


# ── GT source: real CVAT identity, no heuristics ─────────────────────────────

def gt_tracks(xml_path: str) -> Dict[int, List[TrackPoint]]:
    """Per-track head positions from CVAT XML; outside=1 boxes are not visible."""
    root = ET.parse(xml_path).getroot()
    tracks: Dict[int, List[TrackPoint]] = {}
    for track in root.findall("track"):
        points: List[TrackPoint] = []
        for box in track.findall("box"):
            if box.attrib.get("outside", "0") == "1":
                continue
            xtl, ytl = float(box.attrib["xtl"]), float(box.attrib["ytl"])
            xbr, ybr = float(box.attrib["xbr"]), float(box.attrib["ybr"])
            head = Head(cx=(xtl + xbr) / 2.0, cy=(ytl + ybr) / 2.0,
                        height_px=ybr - ytl)
            points.append((int(box.attrib["frame"]), head))
        if points:
            tracks[int(track.attrib["id"])] = sorted(points, key=lambda p: p[0])
    return tracks


def heads_by_frame_from_tracks(
        tracks: Mapping[int, Sequence[TrackPoint]]) -> Dict[int, List[Head]]:
    frames: Dict[int, List[Head]] = defaultdict(list)
    for points in tracks.values():
        for frame_idx, head in points:
            frames[frame_idx].append(head)
    return frames


# ── Episode construction ─────────────────────────────────────────────────────

def _split_on_gaps(points: Sequence[TrackPoint],
                   gap_frames: int) -> List[List[TrackPoint]]:
    """A disappearance longer than the tolerance ends the episode (re-peek = new)."""
    runs: List[List[TrackPoint]] = [[points[0]]]
    for prev, cur in zip(points, points[1:]):
        if cur[0] - prev[0] > gap_frames:
            runs.append([])
        runs[-1].append(cur)
    return runs


def _classify_kind(samples: Sequence[FrameSample], duel_hu: float) -> str:
    """Born near the crosshair = hold; engaged from afar = flick; else unengaged."""
    engaged = any(s.radial_hu <= duel_hu for s in samples)
    if samples[0].radial_hu <= duel_hu:
        return "hold"
    return "flick" if engaged else "unengaged"


def _peak_closing_speed_hu_s(samples: Sequence[FrameSample], fps: float) -> float:
    speeds = [(prev.radial_hu - cur.radial_hu) * fps
              / (cur.frame_idx - prev.frame_idx)
              for prev, cur in zip(samples, samples[1:])]
    return max(speeds, default=0.0)


def _distance_bucket(samples: Sequence[FrameSample], ctx: ClipContext) -> str:
    ratio = statistics.median(s.head_height_px for s in samples) / ctx.height
    if ratio >= CLOSE_MIN_HEIGHT_RATIO:
        return "close"
    return "far" if ratio < FAR_MAX_HEIGHT_RATIO else "mid"


def _multi_from_frame(start: int, end: int,
                      heads_by_frame: HeadsByFrame) -> Optional[int]:
    """First frame within the episode where a second enemy is visible."""
    multi = [f for f, heads in heads_by_frame.items()
             if start <= f <= end and len(heads) >= 2]
    return min(multi) if multi else None


def _build_episode(track_id: int, points: Sequence[TrackPoint],
                   heads_by_frame: HeadsByFrame, ctx: ClipContext,
                   duel_hu: float) -> Episode:
    samples = tuple(sample_frame(frame_idx, head, ctx.crosshair)
                    for frame_idx, head in points)
    start, end = points[0][0], points[-1][0]
    multi_from = _multi_from_frame(start, end, heads_by_frame)
    return Episode(
        track_id=track_id,
        start_frame=start,
        end_frame=end,
        samples=samples,
        kind=_classify_kind(samples, duel_hu),
        distance_bucket=_distance_bucket(samples, ctx),
        multi_enemy=multi_from is not None,
        multi_from_frame=multi_from,
        duel_frames=sum(1 for s in samples if s.radial_hu <= duel_hu),
        peak_closing_speed_hu_s=_peak_closing_speed_hu_s(samples, ctx.fps),
    )


def episodes_from_tracks(tracks: Mapping[int, Sequence[TrackPoint]],
                         heads_by_frame: HeadsByFrame, ctx: ClipContext,
                         duel_hu: float = DEFAULT_DUEL_HU,
                         gap_tolerance_s: float = DEFAULT_GAP_TOLERANCE_S,
                         min_episode_s: float = DEFAULT_MIN_EPISODE_S,
                         ) -> List[Episode]:
    """Tracks -> tagged episodes: split long gaps, drop noise-length runs."""
    gap_frames = max(int(round(gap_tolerance_s * ctx.fps)), 1)
    min_frames = max(int(round(min_episode_s * ctx.fps)), 1)
    episodes = [
        _build_episode(track_id, run, heads_by_frame, ctx, duel_hu)
        for track_id, points in tracks.items()
        for run in _split_on_gaps(points, gap_frames)
        if len(run) >= min_frames
    ]
    return sorted(episodes, key=lambda e: (e.start_frame, e.track_id))


# ── Human-checkable report (done-when: eye-check against the video) ──────────

def format_episodes(episodes: Sequence[Episode], ctx: ClipContext) -> str:
    """One line per episode with frame AND second anchors for manual eye-check."""
    lines = [f"=== ЭПИЗОДЫ: {len(episodes)} (клип {ctx.clip_id}, {ctx.fps:g} fps) ==="]
    for i, ep in enumerate(episodes, start=1):
        t0 = ctx.frame_to_seconds(ep.start_frame)
        t1 = ctx.frame_to_seconds(ep.end_frame)
        if ep.multi_from_frame is None:
            multi = "multi=нет"
        else:
            multi = f"multi=с {ctx.frame_to_seconds(ep.multi_from_frame):.2f} c"
        lines.append(
            f"  #{i:<2} трек {ep.track_id:<2} кадры {ep.start_frame}-{ep.end_frame}"
            f"  ({t0:.2f}-{t1:.2f} c, изм. {len(ep.samples)})"
            f"  {ep.kind:<10} {ep.distance_bucket:<5}"
            f"  дуэль {ep.duel_frames} к."
            f"  {multi}"
            f"  старт {ep.samples[0].radial_hu:.1f} HU"
        )
    return "\n".join(lines)


# ── Entry points (one per frame source) ──────────────────────────────────────

def segment_episodes(heads_by_frame: HeadsByFrame, ctx: ClipContext,
                     duel_hu: float = DEFAULT_DUEL_HU,
                     max_speed_hu_s: float = DEFAULT_MAX_ASSOC_SPEED_HU_S,
                     gap_tolerance_s: float = DEFAULT_GAP_TOLERANCE_S,
                     min_episode_s: float = DEFAULT_MIN_EPISODE_S,
                     ) -> List[Episode]:
    """Episodes from identity-less detections (yolo path)."""
    tracks = associate_tracks(heads_by_frame, ctx, max_speed_hu_s,
                              gap_tolerance_s)
    return episodes_from_tracks(dict(enumerate(tracks)), heads_by_frame, ctx,
                                duel_hu, gap_tolerance_s, min_episode_s)


def episodes_for_gt(xml_path: str, ctx: ClipContext,
                    duel_hu: float = DEFAULT_DUEL_HU,
                    gap_tolerance_s: float = DEFAULT_GAP_TOLERANCE_S,
                    min_episode_s: float = DEFAULT_MIN_EPISODE_S,
                    ) -> List[Episode]:
    """Episodes from CVAT labels using REAL track identity (clean substrate)."""
    tracks = gt_tracks(xml_path)
    return episodes_from_tracks(tracks, heads_by_frame_from_tracks(tracks), ctx,
                                duel_hu, gap_tolerance_s, min_episode_s)
