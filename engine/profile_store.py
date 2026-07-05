"""Stage 5: longitudinal per-player profile — the accumulation multiplier.

One clip gives N duels where any aggregate is a hypothesis; the profile
accumulates metric records across clips per player_id (people are NEVER merged)
and marks statistical confidence explicitly.

Storage is one JSON per player at {store_dir}/{player_id}.json (SQLite is
deliberately skipped at this scale — YAGNI). Re-recording the same clip_id
overwrites its entry, so reruns stay idempotent.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aim_metrics import DEFAULT_DUEL_HU, FrameSample, compute_passport
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.metrics.consistency import compute_consistency
from engine.metrics.correction import compute_correction
from engine.metrics.placement import compute_placement

# Below ANY of these the longitudinal verdict stays a hypothesis.
MIN_CLIPS_FOR_DIAGNOSIS = 2
MIN_EPISODES_FOR_DIAGNOSIS = 8
MIN_DUEL_FRAMES_FOR_DIAGNOSIS = 100


@dataclass(frozen=True)
class PlayerProfile:
    """Cross-clip aggregate for one player (duel metrics duel-frame-weighted)."""
    player_id: str
    clips: int
    episodes_total: int
    flicks_analysed_total: int
    duel_frames_total: int
    duel_mae_hu: Optional[float]
    std_hu: Optional[float]
    y_bias_hu: Optional[float]
    x_bias_hu: Optional[float]
    placement_total: int
    placement_below: int
    placement_above: int
    placement_on_line: int
    x_overshoots: int
    x_undershoots: int
    y_overshoots: int
    y_undershoots: int
    confidence: str            # "diagnosis" | "hypothesis"
    confidence_reason: str


def _nan_to_none(x: float) -> Optional[float]:
    return None if (isinstance(x, float) and math.isnan(x)) else x


# ── Recording one clip ───────────────────────────────────────────────────────

def build_clip_record(ctx: ClipContext, samples: Sequence[FrameSample],
                      episodes: Sequence[Episode],
                      duel_hu: float = DEFAULT_DUEL_HU) -> dict:
    """All Stage 0-4 metrics of one clip, flattened for the JSON store."""
    passport = compute_passport(list(samples), duel_hu=duel_hu)
    consistency = compute_consistency(samples, duel_hu=duel_hu)
    placement = compute_placement(episodes, ctx)
    correction = compute_correction(episodes, ctx, duel_hu=duel_hu)
    kinds = [ep.kind for ep in episodes]
    return {
        "clip_id": ctx.clip_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fps": ctx.fps,
        "frames_measured": passport.frames_measured,
        "duel": {
            "frames": consistency.duel_frames,
            "mae_hu": _nan_to_none(consistency.duel_mae_hu),
            "std_hu": _nan_to_none(consistency.std_hu),
            "iqr_hu": _nan_to_none(consistency.iqr_hu),
            "p95_hu": _nan_to_none(consistency.p95_hu),
            "y_bias_hu": _nan_to_none(passport.y_bias_hu),
            "x_bias_hu": _nan_to_none(passport.x_bias_hu),
        },
        "episodes": {
            "total": len(episodes),
            "flick": kinds.count("flick"),
            "hold": kinds.count("hold"),
            "unengaged": kinds.count("unengaged"),
        },
        "placement": {
            "total": placement.total_episodes,
            "below": placement.n_below,
            "above": placement.n_above,
            "on_line": placement.n_on_line,
            "mean_dy_hu": _nan_to_none(placement.mean_dy_hu),
        },
        "correction": {
            "flicks_analysed": correction.flicks_analysed,
            "x_overshoots": correction.x_overshoots,
            "x_undershoots": correction.x_undershoots,
            "y_overshoots": correction.y_overshoots,
            "y_undershoots": correction.y_undershoots,
        },
    }


def _player_path(store_dir: str, player_id: str) -> Path:
    return Path(store_dir) / f"{player_id}.json"


def load_player(store_dir: str, player_id: str) -> Optional[dict]:
    path = _player_path(store_dir, player_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_clip(store_dir: str, ctx: ClipContext, record: dict) -> Path:
    """Merge the clip record into the player's JSON (same clip_id overwrites)."""
    doc = load_player(store_dir, ctx.player_id) or {
        "player_id": ctx.player_id, "clips": {},
    }
    doc = {**doc, "clips": {**doc["clips"], ctx.clip_id: record}}
    path = _player_path(store_dir, ctx.player_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


# ── Cross-clip aggregation ───────────────────────────────────────────────────

def _weighted_mean(pairs: List[Tuple[Optional[float], int]]) -> Optional[float]:
    """Mean of (value, weight) pairs, skipping missing values."""
    valid = [(v, w) for v, w in pairs if v is not None and w > 0]
    total = sum(w for _, w in valid)
    return sum(v * w for v, w in valid) / total if total else None


def _confidence(clips: int, episodes: int, duel_frames: int) -> Tuple[str, str]:
    lacking = []
    if clips < MIN_CLIPS_FOR_DIAGNOSIS:
        lacking.append(f"клипов {clips} < {MIN_CLIPS_FOR_DIAGNOSIS}")
    if episodes < MIN_EPISODES_FOR_DIAGNOSIS:
        lacking.append(f"эпизодов {episodes} < {MIN_EPISODES_FOR_DIAGNOSIS}")
    if duel_frames < MIN_DUEL_FRAMES_FOR_DIAGNOSIS:
        lacking.append(f"дуэльных кадров {duel_frames} < "
                       f"{MIN_DUEL_FRAMES_FOR_DIAGNOSIS}")
    if lacking:
        return "hypothesis", "мало данных: " + ", ".join(lacking)
    return "diagnosis", "данных достаточно"


def _sum_field(clips: List[dict], section: str, field: str) -> int:
    return sum(c[section][field] for c in clips)


def aggregate_profile(player_doc: dict) -> PlayerProfile:
    clips: List[dict] = list(player_doc["clips"].values())
    duel_weights = [(c["duel"], c["duel"]["frames"]) for c in clips]
    episodes_total = _sum_field(clips, "episodes", "total")
    duel_frames_total = sum(c["duel"]["frames"] for c in clips)
    confidence, reason = _confidence(len(clips), episodes_total,
                                     duel_frames_total)
    return PlayerProfile(
        player_id=player_doc["player_id"],
        clips=len(clips),
        episodes_total=episodes_total,
        flicks_analysed_total=_sum_field(clips, "correction", "flicks_analysed"),
        duel_frames_total=duel_frames_total,
        duel_mae_hu=_weighted_mean([(d["mae_hu"], w) for d, w in duel_weights]),
        std_hu=_weighted_mean([(d["std_hu"], w) for d, w in duel_weights]),
        y_bias_hu=_weighted_mean([(d["y_bias_hu"], w) for d, w in duel_weights]),
        x_bias_hu=_weighted_mean([(d["x_bias_hu"], w) for d, w in duel_weights]),
        placement_total=_sum_field(clips, "placement", "total"),
        placement_below=_sum_field(clips, "placement", "below"),
        placement_above=_sum_field(clips, "placement", "above"),
        placement_on_line=_sum_field(clips, "placement", "on_line"),
        x_overshoots=_sum_field(clips, "correction", "x_overshoots"),
        x_undershoots=_sum_field(clips, "correction", "x_undershoots"),
        y_overshoots=_sum_field(clips, "correction", "y_overshoots"),
        y_undershoots=_sum_field(clips, "correction", "y_undershoots"),
        confidence=confidence,
        confidence_reason=reason,
    )


# ── Human-readable longitudinal report ───────────────────────────────────────

def _fmt_hu(x: Optional[float]) -> str:
    return f"{x:.3f} HU" if x is not None else "—"


def format_profile(p: PlayerProfile) -> str:
    conf = ("ДИАГНОЗ" if p.confidence == "diagnosis" else "ГИПОТЕЗА")
    lines = [
        f"=== ПРОДОЛЬНЫЙ ПРОФИЛЬ: {p.player_id} ===",
        f"  Клипов: {p.clips}, эпизодов: {p.episodes_total}"
        f" (фликов: {p.flicks_analysed_total}),"
        f" дуэльных кадров: {p.duel_frames_total}",
        f"  MAE в дуэли (взвеш.)   : {_fmt_hu(p.duel_mae_hu)};"
        f"  std {_fmt_hu(p.std_hu)}",
        f"  Биасы (дуэль, взвеш.)  : Y {_fmt_hu(p.y_bias_hu)},"
        f"  X {_fmt_hu(p.x_bias_hu)}",
        f"  Пре-айм ниже линии     : {p.placement_below} из {p.placement_total}"
        f" (выше {p.placement_above}, на линии {p.placement_on_line})",
        f"  Коррекция (от фликов)  : X перелёт {p.x_overshoots}/недолёт"
        f" {p.x_undershoots}; Y перелёт {p.y_overshoots}/недолёт {p.y_undershoots}",
        f"  Уверенность: {conf} ({p.confidence_reason})",
    ]
    return "\n".join(lines)
