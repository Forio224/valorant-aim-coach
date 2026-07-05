import React, { useState } from 'react';
import { frameNumberFromUrl } from '../../api';
import { CONFIDENCE_LABELS } from './labels';
import DrillTable from './DrillTable';
import EvidenceThumb from './EvidenceThumb';
import FindingCard from './FindingCard';
import Lightbox from './Lightbox';

/** Индекс улик: номер кадра -> url; заметки берём из evidence движка. */
function buildFrameIndex(analysis) {
  const urls = analysis.evidence_frames ?? [];
  const byNumber = new Map();
  urls.forEach((url) => {
    const number = frameNumberFromUrl(url);
    if (number !== null) byNumber.set(number, { url, number, note: null });
  });
  (analysis.evidence_report?.findings ?? []).forEach((finding) => {
    (finding.evidence ?? []).forEach((entry) => {
      const anchor = entry.frame ?? entry.frame_start;
      const hit = byNumber.get(anchor);
      if (hit && !hit.note) hit.note = entry.note ?? null;
    });
  });
  return byNumber;
}

function framesForNumbers(byNumber, numbers) {
  return (numbers ?? [])
    .map((n) => byNumber.get(n))
    .filter(Boolean);
}

function ClipMeta({ clip, profile }) {
  const seconds = clip.fps ? clip.frame_count / clip.fps : null;
  return (
    <dl className="clip-meta">
      <div><dt>Игрок</dt><dd>{clip.player_id}</dd></div>
      <div><dt>Клип</dt><dd>{clip.clip_id}</dd></div>
      {seconds && (
        <div><dt>Длина</dt><dd>{seconds.toFixed(0)} с · {clip.fps} fps</dd></div>
      )}
      {clip.sens != null && <div><dt>Сенса</dt><dd>{clip.sens}</dd></div>}
      {clip.agent && <div><dt>Агент</dt><dd>{clip.agent}</dd></div>}
      {clip.map_name && <div><dt>Карта</dt><dd>{clip.map_name}</dd></div>}
      {profile && (
        <div>
          <dt>Профиль</dt>
          <dd>
            {profile.clips} {profile.clips === 1 ? 'клип' : 'клипа(ов)'} ·{' '}
            {CONFIDENCE_LABELS[profile.confidence] ?? profile.confidence}
          </dd>
        </div>
      )}
    </dl>
  );
}

function ReportView({ analysis, onReset }) {
  const engine = analysis.evidence_report;
  const coach = analysis.coach_report;
  const isEmptyClip = (engine?.episodes ?? []).length === 0;
  const [openedFrame, setOpenedFrame] = useState(null);
  const byNumber = buildFrameIndex(analysis);
  const engineByMetric = new Map(
    (engine?.findings ?? []).map((f) => [f.metric, f]),
  );

  const usedNumbers = new Set();
  const cards = coach
    ? (coach.findings_explained ?? []).map((item) => {
        const engineFinding = engineByMetric.get(item.metric);
        const frames = framesForNumbers(byNumber, item.evidence_frames);
        frames.forEach((f) => usedNumbers.add(f.number));
        return {
          key: `coach-${item.metric}`,
          metric: item.metric,
          confidence: item.confidence,
          text: item.explanation,
          values: engineFinding?.values,
          frames,
        };
      })
    : (engine?.findings ?? []).map((finding) => {
        const numbers = (finding.evidence ?? [])
          .map((e) => e.frame ?? e.frame_start);
        const frames = framesForNumbers(byNumber, numbers);
        frames.forEach((f) => usedNumbers.add(f.number));
        return {
          key: `engine-${finding.metric}`,
          metric: finding.metric,
          confidence: finding.confidence,
          text: finding.statement,
          values: finding.values,
          frames,
        };
      });

  const spareFrames = [...byNumber.values()]
    .filter((f) => !usedNumbers.has(f.number));

  return (
    <div className="report">
      <section className="panel report-head">
        <div className="report-head-top">
          <h1>Паспорт аима</h1>
          <button type="button" className="btn btn-quiet" onClick={onReset}>
            Разобрать другой клип
          </button>
        </div>
        {engine?.clip && (
          <ClipMeta clip={engine.clip} profile={engine.profile} />
        )}
      </section>

      {isEmptyClip ? (
        <div className="notice notice-hypo" role="status">
          <strong>Врагов в клипе не нашлось.</strong> Детектор не увидел ни
          одной головы противника — движку нечего измерить, а коучу нечего
          объяснять. Проверьте, что это запись боя Valorant, где враги
          появляются в кадре, и попробуйте другой клип.
        </div>
      ) : coach ? (
        <section className="panel summary">
          <h2>Портрет игрока</h2>
          {coach.summary.split(/\n{2,}/).map((para) => (
            <p key={para.slice(0, 40)}>{para}</p>
          ))}
        </section>
      ) : (
        <div className="notice notice-hypo" role="status">
          <strong>Коуч-текст не прошёл проверку достоверности</strong> и был
          отклонён, чтобы не показывать вам выдуманные выводы. Ниже — сырые
          измерения движка; числам можно верить.
          {(analysis.coach_errors ?? []).length > 0 && (
            <details>
              <summary>Что именно не сошлось</summary>
              <ul>
                {analysis.coach_errors.map((err) => <li key={err}>{err}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}

      {!isEmptyClip && (
        <section className="findings">
          <h2>Находки — с доказательствами</h2>
          {cards.map(({ key, ...card }) => (
            <FindingCard key={key} {...card} onOpenFrame={setOpenedFrame} />
          ))}
        </section>
      )}

      {coach?.drills?.length > 0 && <DrillTable drills={coach.drills} />}

      {coach?.caveats?.length > 0 && (
        <section className="panel caveats">
          <h2>Оговорки</h2>
          <ul>
            {coach.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
          </ul>
        </section>
      )}

      {spareFrames.length > 0 && (
        <section className="panel spare-frames">
          <h2>Остальные кадры-улики</h2>
          <div className="finding-frames">
            {spareFrames.map((frame) => (
              <EvidenceThumb key={frame.url} frame={frame}
                             onOpen={setOpenedFrame} />
            ))}
          </div>
        </section>
      )}

      {openedFrame && (
        <Lightbox frame={openedFrame} onClose={() => setOpenedFrame(null)} />
      )}
    </div>
  );
}

export default ReportView;
