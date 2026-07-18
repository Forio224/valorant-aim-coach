"""Task 2 фазы 3: атрибуция цели по намерению (engine.attribution).

Тест-кейсы — вербатим из §Проверка спеки 2026-07-15:
  - фланговый мультикилл (намерение важнее близости — тест на дефект A1);
  - осознанный флик переключает немедленно;
  - дребезг близости НЕ переключает;
  - стрейфящийся враг не крадёт цель;
  - спор помечается и считается;
  - camera_confidence 1/2/3+ = insufficient/hypothesis/diagnosis;
  - gt и yolo дают одинаковую атрибуцию на одних треках.

Синтетика: треки строятся из пиксельных координат голов, без видео и БД.
"""

from typing import List, Sequence, Tuple

from engine.attribution import (
    AttributedSample,
    AttributionResult,
    TargetChoice,
    attribute_targets,
)
from engine.clip_context import ClipContext
from engine.episodes import Episode
from engine.geometry import DEFAULT_DUEL_HU, Head, sample_frame

HEAD_PX = 40.0  # 1 HU = 40 px во всех кейсах (center 960,540 на 1920x1080)


def make_ctx(fps: float = 60.0) -> ClipContext:
    return ClipContext(player_id="p", clip_id="c", fps=fps,
                       width=1920, height=1080, frame_count=100000)


def make_episode(track_id: int,
                 points: Sequence[Tuple[int, float, float]],
                 ctx: ClipContext, *, height_px: float = HEAD_PX,
                 duel_hu: float = DEFAULT_DUEL_HU) -> Episode:
    """points: (frame_idx, cx, cy). Прочие поля Episode атрибуции не нужны."""
    samples = tuple(
        sample_frame(f, Head(cx=cx, cy=cy, height_px=height_px), ctx.crosshair)
        for f, cx, cy in points
    )
    return Episode(
        track_id=track_id,
        start_frame=points[0][0],
        end_frame=points[-1][0],
        samples=samples,
        kind="flick",
        distance_bucket="mid",
        multi_enemy=False,
        multi_from_frame=None,
        duel_frames=sum(1 for s in samples if s.radial_hu <= duel_hu),
        peak_closing_speed_hu_s=0.0,
    )


def attr_by_frame(res: AttributionResult) -> dict:
    return {s.frame_idx: s for s in res.samples}


# ── Фланговый мультикилл: намерение важнее близости (дефект A1) ────────────────

def test_flanking_multikill_follows_camera_not_proximity():
    """Ближний проходит через центр (намерение гасится), дальний стабильно
    приближается за камерой → в финале атрибуция на дальнем, а не на ближнем."""
    ctx = make_ctx()
    cx0 = 960.0
    # near (id=1): проходит через центр (камера уводит его мимо прицела)
    near = make_episode(1, [(f, cx0 + (2 - f) * HEAD_PX, 540.0) for f in range(6)], ctx)
    # far (id=2): 12 HU и стабильно приближается на 1 HU/кадр за той же камерой
    far = make_episode(2, [(f, cx0 + (12 - f) * HEAD_PX, 540.0) for f in range(6)], ctx)
    res = attribute_targets([near, far], ctx)
    by_frame = attr_by_frame(res)
    # финальный кадр: цель — дальний (id=2), несмотря на близость ближнего к центру
    assert by_frame[5].track_id == 2


# ── Осознанный флик переключает немедленно ────────────────────────────────────

def test_deliberate_flick_switches_immediately():
    """Держим ближнюю цель, затем камера резко фликает к дальней → переключение
    в тот же кадр (switch=True), новая цель становится атрибутированной."""
    ctx = make_ctx()
    # A (id=1): у центра, статична в мире, уезжает вместе с камерой при флике
    a_pts = [(0, 980.0, 540.0), (1, 980.0, 540.0), (2, 980.0, 540.0),
             (3, 820.0, 540.0), (4, 660.0, 540.0), (5, 500.0, 540.0)]
    # B (id=2): далеко справа, при флике камера гонит его к центру (−160 px/кадр)
    b_pts = [(0, 1560.0, 540.0), (1, 1560.0, 540.0), (2, 1560.0, 540.0),
             (3, 1400.0, 540.0), (4, 1240.0, 540.0), (5, 1080.0, 540.0)]
    res = attribute_targets([make_episode(1, a_pts, ctx),
                             make_episode(2, b_pts, ctx)], ctx)
    by_frame = attr_by_frame(res)
    assert by_frame[5].track_id == 2                 # цель — B после флика
    assert any(s.switch for s in res.samples)        # был явный переключательный кадр
    assert res.switches >= 1


# ── Дребезг близости НЕ переключает ───────────────────────────────────────────

def test_proximity_jitter_does_not_switch():
    """Цель A удерживается; сосед B чуть приближается СОБСТВЕННЫМ движением при
    стоящей камере (3 головы → медиана камеры устойчива) → цель не меняется."""
    ctx = make_ctx()
    a = make_episode(1, [(f, 980.0, 540.0) for f in range(5)], ctx)   # у центра, статичен
    c = make_episode(3, [(f, 1560.0, 540.0) for f in range(5)], ctx)  # далеко, статичен
    b = make_episode(2, [(f, 1200.0 - 20.0 * f, 540.0) for f in range(5)], ctx)  # дрейф
    res = attribute_targets([a, b, c], ctx)
    by_frame = attr_by_frame(res)
    assert by_frame[4].track_id == 1                 # цель осталась A
    # после первичного захвата A переключений нет
    assert res.switches == 0


# ── Стрейфящийся враг не крадёт цель ──────────────────────────────────────────

def test_strafing_enemy_does_not_steal_target():
    """Собственное (боковое) движение врага не создаёт намерения: стрейфер
    никогда не становится атрибутированной целью, пока держится A."""
    ctx = make_ctx()
    a = make_episode(1, [(f, 980.0, 540.0) for f in range(5)], ctx)   # цель у центра
    c = make_episode(3, [(f, 1560.0, 540.0) for f in range(5)], ctx)  # статичный дальний
    strafer = make_episode(2, [(f, 1200.0 - 20.0 * f, 540.0) for f in range(5)], ctx)
    res = attribute_targets([a, strafer, c], ctx)
    assert all(s.track_id != 2 for s in res.samples if s.track_id is not None)


# ── Спор помечается и считается ───────────────────────────────────────────────

def test_contested_is_marked_and_counted():
    """Два симметричных врага, камера не оценима на кадре рождения (2+ головы,
    нет N−1) → кадр contested: track_id=None, исключён из механики, но СЧИТАЕТСЯ."""
    ctx = make_ctx()
    left = make_episode(1, [(f, 760.0, 540.0) for f in range(3)], ctx)   # −5 HU
    right = make_episode(2, [(f, 1160.0, 540.0) for f in range(3)], ctx)  # +5 HU
    res = attribute_targets([left, right], ctx)
    assert res.contested_frames >= 1
    assert any(s.track_id is None and s.contested for s in res.samples)
    # каждый кадр даёт ровно один сэмпл (спорный тоже посчитан)
    assert len(res.samples) == 3


# ── camera_confidence по числу одновременных голов ────────────────────────────

def test_camera_confidence_scales_with_head_count():
    ctx = make_ctx()
    one = [make_episode(1, [(f, 980.0, 540.0) for f in range(3)], ctx)]
    assert attribute_targets(one, ctx).camera_confidence == "insufficient"

    two = [make_episode(1, [(f, 900.0, 540.0) for f in range(3)], ctx),
           make_episode(2, [(f, 1100.0, 540.0) for f in range(3)], ctx)]
    assert attribute_targets(two, ctx).camera_confidence == "hypothesis"

    three = two + [make_episode(3, [(f, 700.0, 540.0) for f in range(3)], ctx)]
    assert attribute_targets(three, ctx).camera_confidence == "diagnosis"


# ── gt и yolo дают одинаковую атрибуцию на одних треках ────────────────────────

def test_deterministic_same_tracks_same_attribution():
    """Атрибуция работает по трекам (Episode), а не по источнику: одинаковые
    треки → бит-в-бит одинаковый результат (gt/yolo неотличимы для этого слоя)."""
    ctx = make_ctx()
    eps = [make_episode(1, [(f, 980.0, 540.0) for f in range(4)], ctx),
           make_episode(2, [(f, 1400.0 - 40.0 * f, 540.0) for f in range(4)], ctx)]
    r1 = attribute_targets(eps, ctx)
    r2 = attribute_targets(list(eps), ctx)
    assert r1.samples == r2.samples
    assert r1.choices == r2.choices
    assert (r1.switches, r1.contested_frames, r1.camera_confidence) == \
           (r2.switches, r2.contested_frames, r2.camera_confidence)


# ── Регрессии по finding'ам фок-ревью ─────────────────────────────────────────

def test_holds_target_through_intra_episode_occlusion_gap():
    """Цель окклюдирована на кадре внутри своего эпизода (детекторный разрыв,
    мостится в эпизод): держим её сквозь разрыв, чужую голову не подхватываем,
    ложного переключения нет (finding #1)."""
    ctx = make_ctx()
    # T виден 0,1,2,4,5,6 (кадр 3 пропущен — разрыв внутри эпизода 0-6)
    t = make_episode(1, [(f, 1040.0, 540.0) for f in (0, 1, 2, 4, 5, 6)], ctx)
    b = make_episode(2, [(3, 970.0, 540.0)], ctx)   # мелькнул только на кадре 3
    res = attribute_targets([t, b], ctx)
    by_frame = attr_by_frame(res)
    assert 3 not in by_frame                          # окклюзия — кадр не измеряем
    assert all(s.track_id == 1 for s in res.samples)  # B цель не крадёт
    assert res.switches == 0
    assert by_frame[4].track_id == 1                  # T удержан сквозь разрыв


def test_single_common_track_does_not_leak_strafe_as_camera():
    """Камера по ОДНОМУ общему треку недостоверна (стрейф протекает 100%):
    новорождённая вторая голова не крадёт цель через фантомное намерение (#2)."""
    ctx = make_ctx()
    a = make_episode(1, [(f, 900.0 - 40.0 * f, 540.0) for f in range(4)], ctx)
    b = make_episode(2, [(2, 1200.0, 540.0)], ctx)   # рождается на кадре 2
    res = attribute_targets([a, b], ctx)
    by_frame = attr_by_frame(res)
    assert by_frame[2].track_id == 1
    assert 2 not in {s.track_id for s in res.samples}
    assert res.switches == 0


def test_forced_reacquisition_after_target_leaves_is_not_a_switch():
    """Смена цели, ВЫНУЖДЕННАЯ уходом старой (не видна больше), не считается
    переключением-нестабильностью (#3)."""
    ctx = make_ctx()
    a = make_episode(1, [(f, 1040.0, 540.0) for f in range(3)], ctx)     # 0-2
    c = make_episode(3, [(f, 1000.0, 540.0) for f in range(4, 7)], ctx)  # 4-6
    res = attribute_targets([a, c], ctx)
    assert res.switches == 0


# ── Контракты: типы и поля ────────────────────────────────────────────────────

def test_result_shapes():
    ctx = make_ctx()
    eps = [make_episode(1, [(f, 980.0, 540.0) for f in range(3)], ctx)]
    res = attribute_targets(eps, ctx)
    assert isinstance(res, AttributionResult)
    assert all(isinstance(s, AttributedSample) for s in res.samples)
    assert all(isinstance(c, TargetChoice) for c in res.choices)
    # у одиночного трека есть выбор цели (без вердикта)
    assert res.choices and res.choices[0].track_id == 1
