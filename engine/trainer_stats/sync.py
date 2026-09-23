# -*- coding: utf-8 -*-
"""Совмещение лога тренажёра с временной осью видео.

Запись экрана и прогон в тренажёре стартуют независимо, поэтому у клипа и у
лога разные нули. Сдвиг не спрашивается у игрока, а выводится: видео даёт
моменты, когда трек цели пропал (цель уничтожена или исчезла), лог даёт
моменты килов. Сдвиг, при котором эти две последовательности совмещаются
лучше всего, и есть искомый.

Кандидаты сдвига — попарные разности меток, а не сетка с шагом: истинный
сдвиг обязан быть одной из разностей, и перебор получается точным без
выбора шага.

Слабое совпадение означает, что лог не от этого клипа. Тогда сдвиг не
принимается и разбор идёт по видео: приписать клипу чужую статистику хуже,
чем остаться без метрик попаданий.
"""
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from engine.trainer_stats import ShotEvent

DEFAULT_TOLERANCE_S = 0.12      # ~7 кадров при 60 fps: дрожь детектора и лога
DEFAULT_MIN_MATCHES = 3         # меньше — совпадение случая, а не синхронизация
DEFAULT_MIN_RATIO = 0.6         # доля совмещённых от меньшей последовательности


@dataclass(frozen=True)
class SyncResult:
    """Итог привязки лога к видео.

    `reason` заполняется только при отказе и едет в отчёт: игрок должен
    понимать, почему в разборе нет попаданий.
    """
    offset_s: Optional[float]
    matched: int
    total: int
    reason: Optional[str]

    @property
    def ok(self) -> bool:
        return self.offset_s is not None


def _count_matches(video: Sequence[float], log: Sequence[float],
                   offset: float, tolerance_s: float) -> Tuple[int, float]:
    """Сколько меток совмещается при данном сдвиге и с какой общей ошибкой.

    Идём двумя указателями по отсортированным меткам: каждая метка может
    быть использована не более одного раза, иначе один плотный сгусток
    событий «совпал» бы сам с собой многократно.
    """
    matched = 0
    error = 0.0
    i = j = 0
    while i < len(video) and j < len(log):
        delta = video[i] - (log[j] + offset)
        if abs(delta) <= tolerance_s:
            matched += 1
            error += abs(delta)
            i += 1
            j += 1
        elif delta > 0:
            j += 1
        else:
            i += 1
    return matched, error


def estimate_offset(video_times: Sequence[float],
                    log_times: Sequence[float],
                    tolerance_s: float = DEFAULT_TOLERANCE_S,
                    min_matches: int = DEFAULT_MIN_MATCHES,
                    min_ratio: float = DEFAULT_MIN_RATIO) -> SyncResult:
    """Сдвиг, при котором `log_time + offset ≈ video_time`."""
    video = sorted(float(t) for t in video_times)
    log = sorted(float(t) for t in log_times)
    total = min(len(video), len(log))

    if not video or not log:
        return SyncResult(None, 0, total,
                          "нет событий для синхронизации: "
                          "пустой лог или ни одной цели в клипе")

    best_matched = 0
    best_error = 0.0
    best_offset: Optional[float] = None
    for v in video:
        for l in log:
            offset = v - l
            matched, error = _count_matches(video, log, offset, tolerance_s)
            if matched > best_matched or (matched == best_matched
                                          and best_offset is not None
                                          and error < best_error):
                best_matched, best_error, best_offset = matched, error, offset

    if best_matched < min_matches or best_matched < min_ratio * total:
        return SyncResult(
            None, best_matched, total,
            f"лог не удалось привязать к клипу: совпало {best_matched} "
            f"событий из {total}; вероятно, файл статистики от другого "
            f"прогона")

    return SyncResult(best_offset, best_matched, total, None)


def align_events(events: Sequence[ShotEvent],
                 sync: SyncResult) -> Tuple[ShotEvent, ...]:
    """События лога, переложенные на ось видео.

    Без принятого сдвига возвращается пустой кортеж: на оси видео этих
    событий просто нет.
    """
    if not sync.ok:
        return ()
    offset = sync.offset_s or 0.0
    return tuple(
        ShotEvent(t_seconds=e.t_seconds + offset, hit=e.hit, ttk=e.ttk,
                  target_id=e.target_id)
        for e in events)


def target_loss_times(episodes: Sequence, fps: float) -> List[float]:
    """Моменты, когда трек цели пропал — видео-аналог килов из лога.

    Конец эпизода это либо уничтоженная цель, либо потерянный трек; для
    совмещения годится и то и другое, потому что сдвиг ищется по массе
    совпадений, а не по каждому событию.
    """
    if fps <= 0:
        raise ValueError(f"fps должен быть положительным, получено {fps!r}")
    return [ep.end_frame / fps for ep in episodes]
