"""Stage 2: crosshair placement at enemy appearance (metric #1).

Measured on the BIRTH frame of each episode track — the first frame the head is
visible, before the player can have reacted (per the amended roadmap; never on
the first "near-centre" frame, which would flatter the player by construction).

Vertical is the axis that matters for Valorant crosshair placement: keeping aim
on the head LINE. Sign convention inherited from aim_metrics (image y is down):
dy_hu < 0  =>  head above the crosshair  =>  crosshair was BELOW the head line.
"""

import statistics
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from engine.clip_context import ClipContext
from engine.episodes import Episode

# |dy| below this is "on the head line"; beyond it the verdict is below/above.
DEFAULT_PLACEMENT_BAND_HU = 0.5

_VERTICAL_LABELS = {"below": "ниже", "above": "выше", "on_line": "на линии"}


@dataclass(frozen=True)
class PlacementVerdict:
    """Pre-aim verdict for one episode, anchored to its birth frame (evidence)."""
    episode_index: int      # 1-based, matches format_episodes numbering
    frame_idx: int          # track birth frame
    time_s: float
    dx_hu: float
    dy_hu: float
    vertical: str           # "below" | "above" | "on_line" (crosshair vs head line)
    kind: str               # episode kind, for context when reading the report


@dataclass(frozen=True)
class PlacementReport:
    band_hu: float
    total_episodes: int
    n_below: int            # crosshair below the head line (lazy aim)
    n_above: int
    n_on_line: int
    mean_dy_hu: float       # signed; nan when no episodes
    verdicts: Tuple[PlacementVerdict, ...]


def _vertical_verdict(dy_hu: float, band_hu: float) -> str:
    if dy_hu <= -band_hu:
        return "below"      # head above => crosshair below the head line
    if dy_hu >= band_hu:
        return "above"
    return "on_line"


def compute_placement(episodes: Sequence[Episode], ctx: ClipContext,
                      band_hu: float = DEFAULT_PLACEMENT_BAND_HU,
                      ) -> PlacementReport:
    """Pre-aim at the birth frame of every episode."""
    verdicts: List[PlacementVerdict] = []
    for i, ep in enumerate(episodes, start=1):
        birth = ep.samples[0]
        verdicts.append(PlacementVerdict(
            episode_index=i,
            frame_idx=birth.frame_idx,
            time_s=ctx.frame_to_seconds(birth.frame_idx),
            dx_hu=birth.dx_hu,
            dy_hu=birth.dy_hu,
            vertical=_vertical_verdict(birth.dy_hu, band_hu),
            kind=ep.kind,
        ))
    counts = {v: sum(1 for x in verdicts if x.vertical == v)
              for v in ("below", "above", "on_line")}
    return PlacementReport(
        band_hu=band_hu,
        total_episodes=len(verdicts),
        n_below=counts["below"],
        n_above=counts["above"],
        n_on_line=counts["on_line"],
        mean_dy_hu=(statistics.mean(v.dy_hu for v in verdicts)
                    if verdicts else float("nan")),
        verdicts=tuple(verdicts),
    )


def format_placement(report: PlacementReport, ctx: ClipContext) -> str:
    """Done-when shape: «пре-айм: N из M ниже головы на ≥X HU» + кадры-улики."""
    m = report.total_episodes
    lines = [
        f"=== ПРЕ-АЙМ при появлении врага (клип {ctx.clip_id}): {m} эпизодов ===",
        f"  Прицел ниже линии головы (≥{report.band_hu:g} HU): {report.n_below} из {m}",
        f"  Прицел выше: {report.n_above} из {m};  на линии: {report.n_on_line} из {m}",
    ]
    if m:
        lines.append(
            f"  Средний вертикальный офсет: {report.mean_dy_hu:+.2f} HU"
            f"  (минус = прицел ниже голов)"
        )
    for v in report.verdicts:
        lines.append(
            f"  #{v.episode_index:<2} кадр {v.frame_idx} ({v.time_s:.2f} c)"
            f"  dy={v.dy_hu:+.2f} HU  dx={v.dx_hu:+.2f} HU"
            f"  {_VERTICAL_LABELS[v.vertical]:<8} {v.kind}"
        )
    return "\n".join(lines)
