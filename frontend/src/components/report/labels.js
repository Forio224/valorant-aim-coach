// Словари отображения: язык интерфейса един для коуча и фолбэка движка.

export const METRIC_TITLES = {
  placement: 'Пре-айм при появлении врага',
  consistency: 'Стабильность в дуэли',
  bias: 'Смещение прицела в дуэли',
  correction: 'Коррекция на фликах',
};

export const CONFIDENCE_LABELS = {
  diagnosis: 'диагноз',
  hypothesis: 'гипотеза',
  insufficient: 'мало данных',
};

export const PLATFORM_LABELS = {
  kovaaks: "Kovaak's",
  range: 'Полигон',
  ingame: 'В игре',
};

// Подписи чисел движка; порядок = порядок вывода.
export const VALUE_LABELS = {
  duel_frames: 'дуэльных кадров',
  mae_hu: 'ошибка MAE, HU',
  std_hu: 'разброс σ, HU',
  iqr_hu: 'IQR, HU',
  p95_hu: 'p95, HU',
  y_bias_hu: 'Y-биас, HU',
  x_bias_hu: 'X-биас, HU',
  x_abs_hu: '|X|, HU',
  y_abs_hu: '|Y|, HU',
  total: 'эпизодов',
  below: 'ниже линии головы',
  above: 'выше линии',
  on_line: 'на линии',
  mean_dy_hu: 'средний dy, HU',
  band_hu: 'допуск, HU',
  flicks_total: 'фликов',
  flicks_analysed: 'разобрано',
  x_overshoots: 'X-перелётов',
  x_undershoots: 'X-недолётов',
  y_overshoots: 'Y-перелётов',
  y_undershoots: 'Y-недолётов',
};

// Severity-обойма: severity_ratio считает ТОЛЬКО движок (schema 1.3,
// отклонение находки от её собственного порога); фронт лишь рисует.
// Порог = середина обоймы (5 делений), полная обойма = 2× порога.
export const MAG_CELLS = 10;
const MAG_CELLS_PER_THRESHOLD = 5;

/** Вердикт карточки: < 1 — в пороге, 1–2 — за порогом, ≥ 2 — вдвое за. */
export function verdictForSeverity(ratio) {
  if (typeof ratio !== 'number') return null;
  if (ratio >= 2) return 'miss';
  if (ratio >= 1) return 'hypo';
  return 'hit';
}

export function magFilled(ratio) {
  if (typeof ratio !== 'number') return 0;
  return Math.max(0, Math.min(MAG_CELLS,
    Math.round(ratio * MAG_CELLS_PER_THRESHOLD)));
}

export function formatSeverity(ratio) {
  return `${ratio.toFixed(2).replace('.', ',')}×`;
}

export function formatValue(value) {
  if (typeof value !== 'number') return String(value);
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}

/**
 * Главный тезис находки ЧЕЛОВЕЧЕСКИМ языком — детерминированная вёрстка
 * чисел движка (не VLM). Оси: dx/dy = голова − прицел, Y экрана вниз;
 * фразы описывают, где ГОЛОВА относительно прицела — как точка на глифе.
 */
export function humanLead(metric, values) {
  if (!values) return null;
  switch (metric) {
    case 'consistency': {
      if (typeof values.mae_hu !== 'number') return null;
      const heads = values.mae_hu.toFixed(1).replace('.', ',');
      const by = {
        calibration: 'рука при этом стабильна — прицел смещён системно, ' +
          'это калибровка, а не тряска',
        repeatability: 'от попытки к попытке прицел гуляет — страдает ' +
          'повторяемость',
        stable_accurate: 'и стабильно, и точно — придраться не к чему',
      }[values.diagnosis];
      const tail = by ? `; ${by}` : '';
      return `В ближнем бою прицел в среднем в ${heads} высоты головы ` +
        `от цели${tail}.`;
    }
    case 'bias': {
      const { x_bias_hu: x, y_bias_hu: y } = values;
      if (typeof x !== 'number' || typeof y !== 'number') return null;
      const parts = [];
      if (Math.abs(x) > 0.25) parts.push(x > 0 ? 'правее' : 'левее');
      if (Math.abs(y) > 0.25) parts.push(y > 0 ? 'ниже' : 'выше');
      if (parts.length === 0) {
        return 'Заметного постоянного смещения нет: голова врага в среднем ' +
          'у самого перекрестия.';
      }
      return `В дуэли голова врага в среднем оказывается ${parts.join(' и ')} ` +
        'прицела — туда и уходят промахи.';
    }
    case 'placement': {
      const { total, below = 0, above = 0, on_line: onLine = 0 } = values;
      if (!total) return null;
      if (onLine >= below && onLine >= above) {
        return `В ${onLine} из ${total} появлений врага прицел уже ждал ` +
          'на линии головы — хороший пре-айм.';
      }
      if (below >= above) {
        return `В ${below} из ${total} появлений врага прицел ждал ниже ` +
          'линии головы — первый выстрел начинается с доводки вверх.';
      }
      return `В ${above} из ${total} появлений врага прицел ждал выше ` +
        'линии головы — первый выстрел начинается с доводки вниз.';
    }
    case 'correction': {
      const { flicks_analysed: n } = values;
      if (!n) return null;
      const over = (values.x_overshoots ?? 0) + (values.y_overshoots ?? 0);
      const under = (values.x_undershoots ?? 0) + (values.y_undershoots ?? 0);
      if (over === 0 && under === 0) {
        return `Все ${n} разобранных фликов чистые: без перелётов и недолётов.`;
      }
      const bits = [];
      if (over) bits.push(`${over} раз прицел проскочил цель (перелёт)`);
      if (under) bits.push(`${under} раз не доехал (недолёт)`);
      return `На ${n} разобранных фликах ${bits.join(' и ')}.`;
    }
    default:
      return null;
  }
}

/**
 * Минимальный набор цифр движка, которые остаются на виду (не в свёрнутом
 * блоке) — но каждая с пояснением, что она значит для игрока. Полный дамп
 * всех полей всё ещё живёт в labelledValues() под «Числа движка».
 */
export function keyMetricGloss(metric, values) {
  if (!values) return [];
  switch (metric) {
    case 'consistency':
      if (typeof values.mae_hu !== 'number') return [];
      return [{
        label: 'MAE',
        value: `${formatValue(values.mae_hu)} HU`,
        gloss: 'среднее расстояние прицела от головы врага в дуэли — чем меньше, тем точнее',
      }];
    case 'bias':
      if (typeof values.x_bias_hu !== 'number' || typeof values.y_bias_hu !== 'number') return [];
      return [{
        label: 'Биас X / Y',
        value: `${formatValue(values.x_bias_hu)} / ${formatValue(values.y_bias_hu)} HU`,
        gloss: 'среднее направление промаха относительно прицела — 0 значит промаха нет',
      }];
    case 'placement':
      if (typeof values.total !== 'number') return [];
      return [{
        label: 'На линии головы',
        value: `${values.on_line ?? 0} из ${values.total}`,
        gloss: 'в скольких появлениях врага прицел уже ждал на нужной высоте',
      }];
    case 'correction': {
      if (typeof values.flicks_analysed !== 'number') return [];
      const over = (values.x_overshoots ?? 0) + (values.y_overshoots ?? 0);
      const under = (values.x_undershoots ?? 0) + (values.y_undershoots ?? 0);
      return [{
        label: 'Перелёт / недолёт',
        value: `${over} / ${under} из ${values.flicks_analysed}`,
        gloss: 'сколько раз прицел проскакивал цель или не доезжал на быстрых доводках',
      }];
    }
    default:
      return [];
  }
}

/** Пары [подпись, значение] в порядке словаря; незнакомые ключи — в хвост. */
export function labelledValues(values) {
  if (!values) return [];
  const known = Object.keys(VALUE_LABELS)
    .filter((key) => key in values)
    .map((key) => [VALUE_LABELS[key], formatValue(values[key])]);
  const rest = Object.entries(values)
    .filter(([key]) => !(key in VALUE_LABELS) && key !== 'diagnosis')
    .map(([key, value]) => [key, formatValue(value)]);
  return [...known, ...rest];
}
