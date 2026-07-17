# -*- coding: utf-8 -*-
"""Детерминированный каталог дриллов + числовые критерии успеха (Фаза 1).

Движок владеет каталогом и числами; VLM выбирает drill_id и объясняет.
Имена/пороги сценариев — Voltaic S5 (evxl.app, 2026-07): consistency→ww5t
(сустейн-повторяемость), bias→1wNts (точная одиночная постановка, целей
меньше с тиром), correction→Pasu (реактивный флик). placement — in-game
(у Voltaic нет пре-айм-сценария). drill_id стабильны — Фаза 2 ключуется на
них, переименование рвёт историю. Пороги = верхние ранги тиров S5.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from coach.schema import Drill, DrillSelection, SuccessCriterion
from engine.metrics.criterion import (CORE_METRICS, CONSISTENCY_IMPROVEMENT,
                                       compute_metric_criterion)



@dataclass(frozen=True)
class CatalogDrill:
    """Одно упражнение каталога: id, название, платформа, тир, метрика, доза.

    rank_thresholds — пороги рангов Voltaic S5 для сценария этого тира
    (ранг→score); None для in-game placement (у Voltaic нет пре-айма).
    Читается Фазой 2C (двухсигнальная прогрессия), в Фазе 1 не потребляется."""
    drill_id: str
    name: str
    platform: str          # "kovaaks" | "range" | "ingame"
    tier: int               # 1 Novice | 2 Intermediate | 3 Advanced
    metric: str
    dose: str               # доза-плейсхолдер; пользователь тюнит доменно
    instruction: str        # фокус инструкции (разводит bias/consistency)
    rank_thresholds: Optional[Dict[str, int]] = None


# Семантика тиров = сложность механики в тренажёре (перенос в игру меряет
# движок на клипах отдельно). placement — исключение: все тиры in-game.
CATALOG: Dict[str, List[CatalogDrill]] = {
    "placement": [
        CatalogDrill("placement_t1_range_preaim_walk",
                     "Range: pre-aim walk на уровне головы", "range", 1,
                     "placement", "5 минут разминкой",
                     "Иди по полигону, держа прицел строго на линии головы, без стрельбы."),
        CatalogDrill("placement_t2_valorant_clear_angles",
                     "Valorant: clear angles (пре-айм типовых углов)", "ingame", 2,
                     "placement", "10 минут перед сессией",
                     "Пре-айм типовых углов сайта на уровне головы до входа."),
        CatalogDrill("placement_t3_valorant_deathmatch",
                     "Valorant Deathmatch: пре-айм под давлением", "ingame", 3,
                     "placement", "1 матч DM в день",
                     "Держи прицел на линии головы в движении и под давлением."),
    ],
    "consistency": [
        CatalogDrill("consistency_t1_vt_ww5t_novice",
                     "VT ww5t Novice S5", "kovaaks", 1,
                     "consistency", "3 подхода по 5 минут",
                     "Сустейн-повторяемость: держи темп, минимизируй разброс попаданий.",
                     {"iron": 990, "bronze": 1090, "silver": 1190, "gold": 1290}),
        CatalogDrill("consistency_t2_vt_ww5t_intermediate",
                     "VT ww5t Intermediate S5", "kovaaks", 2,
                     "consistency", "3 подхода по 5 минут",
                     "Та же повторяемость под возросшим темпом/точностью.",
                     {"platinum": 1310, "diamond": 1400, "jade": 1490, "master": 1560}),
        CatalogDrill("consistency_t3_vt_ww5t_advanced",
                     "VT ww5t Advanced S5", "kovaaks", 3,
                     "consistency", "3 подхода по 5 минут",
                     "Повторяемость на соревновательном темпе.",
                     {"grandmaster": 1510, "nova": 1610, "astra": 1720, "celestial": 1860}),
    ],
    "bias": [
        CatalogDrill("bias_t1_vt_1w4ts_novice",
                     "VT 1w4ts Novice S5", "kovaaks", 1,
                     "bias", "3 подхода по 5 минут",
                     "Точная одиночная постановка — здесь видно систематическое смещение прицела.",
                     {"iron": 820, "bronze": 915, "silver": 1010, "gold": 1110}),
        CatalogDrill("bias_t2_vt_1w3ts_intermediate",
                     "VT 1w3ts Intermediate S5", "kovaaks", 2,
                     "bias", "3 подхода по 5 минут",
                     "Меньше целей, выше требования к точной постановке.",
                     {"platinum": 1120, "diamond": 1220, "jade": 1300, "master": 1380}),
        CatalogDrill("bias_t3_vt_1w2ts_advanced",
                     "VT 1w2ts Advanced S5", "kovaaks", 3,
                     "bias", "3 подхода по 5 минут",
                     "Одиночная постановка на соревновательной точности.",
                     {"grandmaster": 1320, "nova": 1420, "astra": 1520, "celestial": 1620}),
    ],
    "correction": [
        CatalogDrill("correction_t1_vt_pasu_novice",
                     "VT Pasu Novice S5", "kovaaks", 1,
                     "correction", "3 подхода по 5 минут",
                     "Реактивный флик к цели: гаси перелёт доводкой, не проскакивай.",
                     {"iron": 555, "bronze": 660, "silver": 745, "gold": 800}),
        CatalogDrill("correction_t2_vt_pasu_intermediate",
                     "VT Pasu Intermediate S5", "kovaaks", 2,
                     "correction", "3 подхода по 5 минут",
                     "Тот же флик под возросшей амплитудой/темпом.",
                     {"platinum": 770, "diamond": 850, "jade": 930, "master": 980}),
        CatalogDrill("correction_t3_vt_pasu_advanced",
                     "VT Pasu Advanced S5", "kovaaks", 3,
                     "correction", "3 подхода по 5 минут",
                     "Флик близко к соревновательной механике.",
                     {"grandmaster": 910, "nova": 1020, "astra": 1110, "celestial": 1240}),
    ],
}

_CATALOG_BY_ID: Dict[str, CatalogDrill] = {
    d.drill_id: d for drills in CATALOG.values() for d in drills
}


def get_catalog_drill(drill_id: str) -> Optional[CatalogDrill]:
    return _CATALOG_BY_ID.get(drill_id)


def _tier1_core_drills() -> List[CatalogDrill]:
    """Tier-1 дрилл каждой core-метрики (первый клип всегда tier 1)."""
    return [next(d for d in CATALOG[metric] if d.tier == 1)
            for metric in CORE_METRICS]


def menu_drill_ids() -> frozenset:
    """Множество допустимых drill_id для первого клипа (только tier-1 core).

    Валидатор гейтит выбор VLM по нему: tier механически зафиксирован на 1,
    а не оставлен на доверие промпту (Фаза 2 ключуется на drill_id)."""
    return frozenset(cd.drill_id for cd in _tier1_core_drills())


def menu_for_prompt() -> str:
    """Меню tier-1 core-дриллов для промпта (первый клип всегда tier 1)."""
    lines = ["Меню дриллов (выбирай drill_id ТОЛЬКО отсюда):"]
    for cd in _tier1_core_drills():
        lines.append(f"- {cd.drill_id} (метрика {cd.metric}): {cd.name}")
    return "\n".join(lines)


def build_criterion(metric: str, values: dict) -> SuccessCriterion:
    """Детерминированный критерий: числа из общего хелпера движка (engine/),
    человеческий text — здесь."""
    m = compute_metric_criterion(metric, values)
    vk, comparator = m["value_key"], m["comparator"]
    target, baseline = m["target"], m["baseline"]
    if metric == "placement":
        if baseline is None:
            text = "Нужен ещё клип для числового критерия пре-айма."
        else:
            text = (f"Довести число появлений с прицелом ниже линии головы до "
                    f"≤ {int(target)} из {values['total']} (сейчас {int(baseline)}); "
                    f"средний вертикальный промах — к нулю.")
    elif metric == "consistency":
        if baseline is None:
            text = "Нужен ещё клип для числового критерия точности."
        else:
            text = (f"Средняя ошибка в дуэли < {target} HU "
                    f"(−{int(CONSISTENCY_IMPROVEMENT * 100)}% к текущим "
                    f"{baseline} HU) на следующем клипе.")
    elif metric == "bias":
        if baseline is None:
            text = "Нужен ещё клип для числового критерия смещения."
        else:
            text = (f"Систематическое вертикальное смещение |Y| < {target} HU "
                    f"(вдвое меньше текущих {baseline} HU).")
    elif metric == "correction":
        if not m["directional_meaningful"]:
            text = ("Держать чистые флики без перелёта и недолёта на следующем "
                    "клипе.")
        else:
            count = int(baseline)
            analysed = values.get("flicks_analysed", 0)
            axis = vk[0].upper()
            kind = "перелёт" if "overshoots" in vk else "недолёт"
            text = (f"Снизить долю {kind}ов по оси {axis}: сейчас {count} из "
                    f"{analysed} фликов — двигать в сторону чистых фликов "
                    f"(прокси-метрика, без жёсткого порога).")
    else:
        raise ValueError(f"неизвестная метрика критерия: {metric}")
    return SuccessCriterion(metric=metric, value_key=vk, comparator=comparator,
                            target=target, baseline=baseline, text=text)


def assemble_drill(selection: DrillSelection, finding: dict) -> Drill:
    """Финальный Drill: имя/платформа/доза/тир из каталога, критерий из values."""
    cd = _CATALOG_BY_ID[selection.drill_id]
    criterion = build_criterion(cd.metric, finding.get("values", {}))
    return Drill(
        priority=selection.priority,
        drill_id=cd.drill_id,
        name=cd.name,
        platform=cd.platform,
        tier=cd.tier,
        dose=cd.dose,
        target_metric=cd.metric,
        rationale=selection.rationale,
        success_criterion=criterion.text,
        criterion=criterion,
    )


@dataclass
class FinalizedPlan:
    """Собранный план: финальные дриллы + добавочные оговорки (честность)."""
    drills: List[Drill] = field(default_factory=list)
    extra_caveats: List[str] = field(default_factory=list)


def finalize_plan(selections: Sequence[DrillSelection],
                  findings: Sequence[dict]) -> FinalizedPlan:
    """Сборка + правило честности: без единого диагноза план урезается до топ-2."""
    by_metric = {f["metric"]: f for f in findings}
    drills: List[Drill] = []
    for sel in selections:
        cd = _CATALOG_BY_ID.get(sel.drill_id)
        if cd is None or cd.metric not in by_metric:
            continue                       # валидатор уже страхует; защитно
        drills.append(assemble_drill(sel, by_metric[cd.metric]))
    drills.sort(key=lambda d: d.priority)
    extra: List[str] = []
    has_diagnosis = any(f.get("confidence") == "diagnosis" for f in findings)
    if not has_diagnosis:
        # CTA нужен всегда, когда всё держится на гипотезах — «запиши ещё клип»
        # ценнее всего именно тут; урезаем до топ-2 только если дриллов больше.
        trimmed = len(drills) > 2
        if trimmed:
            drills = drills[:2]
        head = ("план сокращён до 1–2 главных гипотез"
                if trimmed else "план держится на гипотезах")
        extra.append(
            f"Пока ни один вывод не дотянул до уверенного диагноза — {head}. "
            "Запиши ещё 1–2 клипа, чтобы движок подтвердил закономерности.")
    return FinalizedPlan(drills=drills, extra_caveats=extra)
