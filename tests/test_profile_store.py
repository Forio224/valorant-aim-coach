"""Stage 5 tests: longitudinal per-player profile (JSON store, cross-clip).

Per-player from day one: people are NEVER merged into one portrait.
Confidence marking: few data -> hypothesis, not diagnosis.
"""

import json
from pathlib import Path

import pytest

from aim_metrics import Head
from engine.clip_context import ClipContext
from engine.episodes import episodes_for_gt, segment_episodes
from engine.profile_store import (
    PlayerProfile,
    aggregate_profile,
    build_clip_record,
    format_profile,
    load_player,
    save_clip,
)
from engine.version import METRICS_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent
H = 20.0


def make_ctx(player_id: str, clip_id: str) -> ClipContext:
    return ClipContext(player_id=player_id, clip_id=clip_id, fps=60.0,
                       width=1920, height=1080, frame_count=600)


def synthetic_clip(radial_hu: float, n_frames: int = 30, n_episodes: int = 1):
    """Episodes of heads sitting at a constant radial offset (pure-X)."""
    frames: dict = {}
    for e in range(n_episodes):
        start = e * (n_frames + 60)            # spaced out -> separate episodes
        for i in range(n_frames):
            frames.setdefault(start + i, []).append(
                Head(cx=960.0 + radial_hu * H, cy=540.0, height_px=H))
    ctx = make_ctx("p", "c")
    episodes = segment_episodes(frames, ctx)
    samples = [s for ep in episodes for s in ep.samples]
    return samples, episodes


# ── Recording clips ──────────────────────────────────────────────────────────


def test_save_creates_player_json(tmp_path):
    ctx = make_ctx("p1", "cA")
    samples, episodes = synthetic_clip(1.5)
    save_clip(str(tmp_path), ctx, build_clip_record(ctx, samples, episodes))

    doc = json.loads((tmp_path / "p1.json").read_text(encoding="utf-8"))
    assert doc["player_id"] == "p1"
    assert doc["clips"]["cA"]["duel"]["mae_hu"] == pytest.approx(1.5)
    assert doc["clips"]["cA"]["fps"] == 60.0


def test_resaving_same_clip_overwrites_not_duplicates(tmp_path):
    ctx = make_ctx("p1", "cA")
    samples, episodes = synthetic_clip(1.5)
    record = build_clip_record(ctx, samples, episodes)
    save_clip(str(tmp_path), ctx, record)
    save_clip(str(tmp_path), ctx, record)
    doc = load_player(str(tmp_path), "p1")
    assert len(doc["clips"]) == 1


def test_players_are_never_merged(tmp_path):
    for player in ("p1", "p2"):
        ctx = make_ctx(player, "cA")
        samples, episodes = synthetic_clip(1.0)
        save_clip(str(tmp_path), ctx, build_clip_record(ctx, samples, episodes))
    assert (tmp_path / "p1.json").exists() and (tmp_path / "p2.json").exists()
    assert aggregate_profile(load_player(str(tmp_path), "p1")).clips == 1


# ── Cross-clip aggregation ───────────────────────────────────────────────────


def test_two_clips_accumulate_with_duel_frame_weighting(tmp_path):
    for clip_id, radial in (("cA", 1.5), ("cB", 0.5)):
        ctx = make_ctx("p1", clip_id)
        samples, episodes = synthetic_clip(radial, n_frames=30)
        save_clip(str(tmp_path), ctx, build_clip_record(ctx, samples, episodes))

    profile = aggregate_profile(load_player(str(tmp_path), "p1"))
    assert profile.clips == 2
    assert profile.duel_frames_total == 60
    assert profile.duel_mae_hu == pytest.approx(1.0)   # equal weights 30/30


def test_single_clip_profile_is_hypothesis(tmp_path):
    ctx = make_ctx("p1", "cA")
    samples, episodes = synthetic_clip(1.0, n_frames=60, n_episodes=8)
    save_clip(str(tmp_path), ctx, build_clip_record(ctx, samples, episodes))
    profile = aggregate_profile(load_player(str(tmp_path), "p1"))
    assert profile.confidence == "hypothesis"


def test_enough_clips_episodes_and_frames_is_diagnosis(tmp_path):
    for clip_id in ("cA", "cB"):
        ctx = make_ctx("p1", clip_id)
        samples, episodes = synthetic_clip(1.0, n_frames=60, n_episodes=4)
        save_clip(str(tmp_path), ctx, build_clip_record(ctx, samples, episodes))
    profile = aggregate_profile(load_player(str(tmp_path), "p1"))
    assert profile.episodes_total == 8
    assert profile.duel_frames_total == 480
    assert profile.confidence == "diagnosis"


# ── Версионирование методики (Фаза 3) ────────────────────────────────────────


def test_build_clip_record_stamps_current_metrics_version(tmp_path):
    ctx = make_ctx("p1", "cA")
    samples, episodes = synthetic_clip(1.0)
    record = build_clip_record(ctx, samples, episodes)
    assert record["metrics_version"] == METRICS_VERSION


def test_stale_metrics_version_excluded_from_aggregate(tmp_path):
    """Запись по прежней методике (без поля = v1) не входит в агрегат, а причина
    названа в confidence_reason — иначе смена методики смешалась бы с прогрессом."""
    ctx = make_ctx("p1", "cA")
    samples, episodes = synthetic_clip(1.0, n_frames=60, n_episodes=8)
    save_clip(str(tmp_path), ctx, build_clip_record(ctx, samples, episodes))

    doc = load_player(str(tmp_path), "p1")
    stale = dict(next(iter(doc["clips"].values())))
    stale.pop("metrics_version", None)           # эмулируем запись v1
    doc["clips"]["old_clip"] = stale

    profile = aggregate_profile(doc)
    assert profile.clips == 1                     # только текущая версия
    assert "прежней методике" in profile.confidence_reason


# ── Report text ──────────────────────────────────────────────────────────────


def test_format_profile_names_player_clips_confidence(tmp_path):
    ctx = make_ctx("p1", "cA")
    samples, episodes = synthetic_clip(1.0)
    save_clip(str(tmp_path), ctx, build_clip_record(ctx, samples, episodes))
    text = format_profile(aggregate_profile(load_player(str(tmp_path), "p1")))
    assert "p1" in text
    assert "1" in text                       # clip count
    assert "гипотеза" in text.lower()        # confidence in plain words


# ── Real clips: friend accumulates 2, author stays separate ─────────────────


@pytest.mark.integration
def test_friend_accumulates_author_differs(tmp_path):
    def record(player_id, clip_stem):
        xml = PROJECT_ROOT / "dataset1" / f"{clip_stem}.xml"
        ctx = make_ctx(player_id, clip_stem)
        episodes = episodes_for_gt(str(xml), ctx)
        samples = [s for ep in episodes for s in ep.samples]
        save_clip(str(tmp_path), ctx,
                  build_clip_record(ctx, samples, episodes))

    record("friend", "clip2")
    record("friend", "clip3")
    record("author", "output_clip")

    friend = aggregate_profile(load_player(str(tmp_path), "friend"))
    author = aggregate_profile(load_player(str(tmp_path), "author"))
    assert friend.clips == 2 and author.clips == 1
    assert friend.episodes_total == 9 and author.episodes_total == 6
    assert author.confidence == "hypothesis"   # one clip is never a diagnosis
    # Differential: the profiles are genuinely different portraits.
    assert friend.y_overshoots != author.y_overshoots or \
        friend.duel_mae_hu != pytest.approx(author.duel_mae_hu, abs=1e-6)
