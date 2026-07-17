# -*- coding: utf-8 -*-
"""Тупой добытчик истории (Фаза 2B): снимки из сессий, без БД."""
from backend.services.history_provider import build_clip_snapshots


def _session(clip_id, created_at, findings, drills=None):
    return {
        "clip_id": clip_id, "created_at": created_at,
        "evidence_report": {"findings": findings},
        "coach_report": ({"drills": drills} if drills is not None else None),
    }


def _f(metric, values, conf="diagnosis"):
    return {"metric": metric, "values": values, "confidence": conf}


def test_excludes_current_and_orders_by_time():
    sessions = [
        _session("c2", "2026-07-02T00:00:00", [_f("consistency", {"mae_hu": 4.6})]),
        _session("cur", "2026-07-03T00:00:00", [_f("consistency", {"mae_hu": 4.2})]),
        _session("c1", "2026-07-01T00:00:00", [_f("consistency", {"mae_hu": 5.0})]),
    ]
    snaps = build_clip_snapshots(sessions, exclude_clip_id="cur")
    assert [s["clip_id"] for s in snaps] == ["c1", "c2"]     # текущий исключён, сорт
    assert snaps[0]["findings"]["consistency"]["values"]["mae_hu"] == 5.0


def test_dedup_by_clip_id_keeps_latest():
    sessions = [
        _session("c1", "2026-07-01T00:00:00", [_f("consistency", {"mae_hu": 5.0})]),
        _session("c1", "2026-07-05T00:00:00", [_f("consistency", {"mae_hu": 4.0})]),
    ]
    snaps = build_clip_snapshots(sessions, exclude_clip_id="cur")
    assert len(snaps) == 1
    assert snaps[0]["findings"]["consistency"]["values"]["mae_hu"] == 4.0


def test_assignments_from_coach_drills():
    sessions = [_session(
        "c1", "2026-07-01T00:00:00", [_f("consistency", {"mae_hu": 5.0})],
        drills=[{"target_metric": "consistency",
                 "drill_id": "consistency_t1_vt_ww5t_novice"}])]
    snap = build_clip_snapshots(sessions, "cur")[0]
    assert snap["assignments"] == {"consistency": "consistency_t1_vt_ww5t_novice"}


def test_coach_failed_session_has_empty_assignments():
    sessions = [_session("c1", "2026-07-01T00:00:00",
                         [_f("consistency", {"mae_hu": 5.0})], drills=None)]
    snap = build_clip_snapshots(sessions, "cur")[0]
    assert snap["assignments"] == {} and "consistency" in snap["findings"]


def test_session_without_evidence_report_skipped():
    sessions = [{"clip_id": "c1", "created_at": "2026-07-01T00:00:00",
                 "evidence_report": None, "coach_report": None}]
    assert build_clip_snapshots(sessions, "cur") == []
