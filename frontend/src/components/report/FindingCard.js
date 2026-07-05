import React from 'react';
import OffsetGlyph from '../OffsetGlyph';
import EvidenceThumb from './EvidenceThumb';
import {
  CONFIDENCE_LABELS, METRIC_TITLES, humanLead, keyMetricGloss, labelledValues,
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

/**
 * Одна находка. Порядок подачи: человеческий тезис из чисел движка →
 * объяснение коуча → минимальная аннотированная цифра (keyMetricGloss) →
 * улики; полный дамп HU-чисел спрятан в «Числа движка».
 */
function FindingCard({ metric, confidence, text, values, frames, onOpenFrame }) {
  const glyph = glyphFor(metric, values);
  const lead = humanLead(metric, values);
  const gloss = keyMetricGloss(metric, values);
  const pairs = labelledValues(values);

  return (
    <article className={`finding is-${confidence}`}>
      <header className="finding-head">
        <h3>{METRIC_TITLES[metric] ?? metric}</h3>
        <ConfidenceBadge confidence={confidence} />
      </header>

      <div className="finding-body">
        <div className="finding-text">
          {lead && <p className="finding-lead">{lead}</p>}
          <p>{text}</p>
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
