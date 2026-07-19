import React from 'react';
import useReveal from '../../hooks/useReveal';
import OffsetGlyph from '../OffsetGlyph';
import EvidenceThumb from './EvidenceThumb';
import {
  CONFIDENCE_LABELS, MAG_CELLS, METRIC_TITLES, formatSeverity, humanLead,
  keyMetricGloss, labelledValues, magFilled, verdictForSeverity,
} from './labels';

function ConfidenceBadge({ confidence }) {
  return (
    <span className={`badge badge-${confidence}`}>
      {CONFIDENCE_LABELS[confidence] ?? confidence}
    </span>
  );
}

/** Смещение для глифа: у биаса обе оси, у пре-айма только вертикаль. */
function glyphFor(metric, values) {
  if (!values) return null;
  if (metric === 'bias' &&
      typeof values.x_bias_hu === 'number' &&
      typeof values.y_bias_hu === 'number') {
    return { dxHu: values.x_bias_hu, dyHu: values.y_bias_hu,
             label: 'точка — где в среднем голова врага' };
  }
  if (metric === 'placement' && typeof values.mean_dy_hu === 'number') {
    return { dxHu: 0, dyHu: values.mean_dy_hu,
             label: 'точка — голова в момент появления' };
  }
  return null;
}

/** Severity-обойма: число движка + деления, заряжающиеся при появлении. */
function SeverityMag({ ratio }) {
  const filled = magFilled(ratio);
  return (
    <div className="mag">
      <div className="num">
        {formatSeverity(ratio)}
        <small>от порога</small>
      </div>
      <div className="cells" aria-hidden="true">
        {Array.from({ length: MAG_CELLS }, (_, i) => (
          <i key={i} className={i < filled ? 'f' : undefined} />
        ))}
      </div>
    </div>
  );
}

/**
 * Одна находка. Порядок подачи: человеческий тезис из чисел движка →
 * объяснение коуча → severity-обойма → аннотированная цифра
 * (keyMetricGloss) → улики; полный дамп HU-чисел спрятан в «Числа движка».
 * Вердикт (цвет уголков и обоймы) — из severity_ratio движка.
 */
function FindingCard({
  metric, confidence, text, values, severityRatio, frames, onOpenFrame,
}) {
  const [ref, inView] = useReveal();
  const glyph = glyphFor(metric, values);
  const lead = humanLead(metric, values);
  const gloss = keyMetricGloss(metric, values);
  const pairs = labelledValues(values);
  const verdict = verdictForSeverity(severityRatio);
  const verdictClass = verdict ? ` v-${verdict}` : '';
  const spanClass = frames.length > 0 ? ' span2' : '';

  return (
    <article
      ref={ref}
      className={`finding hud rv${verdictClass}${spanClass}${inView ? ' in' : ''}`}
    >
      <span className="c" aria-hidden="true" />
      <header className="finding-head">
        <h3>{METRIC_TITLES[metric] ?? metric}</h3>
        <ConfidenceBadge confidence={confidence} />
      </header>

      <div className="finding-body">
        <div className="finding-text">
          {lead && <p className="finding-lead">{lead}</p>}
          <p>{text}</p>
          {typeof severityRatio === 'number' && (
            <SeverityMag ratio={severityRatio} />
          )}
          {gloss.length > 0 && (
            <dl className="finding-gloss">
              {gloss.map(({ label, value, gloss: hint }) => (
                <div key={label} className="gloss-item">
                  <dt>
                    <span className="gloss-label">{label}</span>{' '}
                    <span className="gloss-value">{value}</span>
                  </dt>
                  <dd>{hint}</dd>
                </div>
              ))}
            </dl>
          )}
          {pairs.length > 0 && (
            <details className="tech-values">
              <summary>Числа движка (в HU — высотах головы цели)</summary>
              <dl className="finding-values">
                {pairs.map(([label, value]) => (
                  <div key={label} className="value-pair">
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </div>
        {glyph && <OffsetGlyph {...glyph} />}
      </div>

      {frames.length > 0 && (
        <div className="finding-frames">
          {frames.map((frame) => (
            <EvidenceThumb key={frame.url} frame={frame} onOpen={onOpenFrame} />
          ))}
        </div>
      )}
    </article>
  );
}

export default FindingCard;
