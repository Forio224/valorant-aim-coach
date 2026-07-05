import React from 'react';

// Сигнатурный элемент: реальное смещение из данных движка, нарисованное
// на прицеле. Кольцо = 1 HU (высота головы цели), точка = где в среднем
// была голова относительно перекрестия (ось Y экрана направлена вниз).
const SIZE = 104;
const HU_RADIUS = 30; // px на 1 HU
const MAX_HU = 1.45; // дальше точка прижимается к краю кольца-лимита

function OffsetGlyph({ dxHu = 0, dyHu = 0, label }) {
  const c = SIZE / 2;
  const magnitude = Math.hypot(dxHu, dyHu);
  const clamp = magnitude > MAX_HU ? MAX_HU / magnitude : 1;
  const x = c + dxHu * HU_RADIUS * clamp;
  const y = c + dyHu * HU_RADIUS * clamp;
  const offTarget = magnitude > 0.25; // порог вердикта движка по биасу

  return (
    <figure className="offset-glyph">
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`Смещение головы от прицела: ${dxHu >= 0 ? '+' : ''}${dxHu.toFixed(2)} по X, ${dyHu >= 0 ? '+' : ''}${dyHu.toFixed(2)} по Y, в HU`}
      >
        <circle cx={c} cy={c} r={HU_RADIUS} className="glyph-ring" />
        <line x1={c} y1={6} x2={c} y2={SIZE - 6} className="glyph-cross" />
        <line x1={6} y1={c} x2={SIZE - 6} y2={c} className="glyph-cross" />
        <circle
          cx={x}
          cy={y}
          r={5}
          className={offTarget ? 'glyph-dot is-miss' : 'glyph-dot is-hit'}
        />
      </svg>
      <figcaption>
        {label ?? '1 HU = высота головы'}
      </figcaption>
    </figure>
  );
}

export default OffsetGlyph;
