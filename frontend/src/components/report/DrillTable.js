import React from 'react';
import useReveal from '../../hooks/useReveal';
import { METRIC_TITLES, PLATFORM_LABELS } from './labels';

/** Один контракт: номер = приоритет коуча, печать = критерий успеха. */
function ContractCard({ drill }) {
  const [ref, inView] = useReveal();
  return (
    <article ref={ref} className={`contract rv${inView ? ' in' : ''}`}>
      <div className="no">{String(drill.priority).padStart(2, '0')}</div>
      <h3>{drill.name}</h3>
      <div className="contract-chips">
        <span className={`chip chip-${drill.platform}`}>
          {PLATFORM_LABELS[drill.platform] ?? drill.platform}
        </span>
        {drill.tier != null && <span className="chip">tier {drill.tier}</span>}
      </div>
      <div className="dose">{drill.dose}</div>
      {drill.rationale && (
        <p className="contract-rationale">{drill.rationale}</p>
      )}
      <div className="contract-target">
        лечит: {METRIC_TITLES[drill.target_metric] ?? drill.target_metric}
      </div>
      <div className="stamp">закрыт, когда {drill.success_criterion}</div>
    </article>
  );
}

function DrillTable({ drills }) {
  const ordered = [...drills].sort((a, b) => a.priority - b.priority);

  return (
    <section className="drills">
      <h2>
        Контракты на завтра
        <small>по одному дриллу на проблему</small>
      </h2>
      <p className="section-lede">
        Номер — приоритет. Печать — критерий успеха: когда он выполнен,
        контракт закрыт и дрилл можно бросать.
      </p>
      <div className="contracts">
        {ordered.map((drill) => (
          <ContractCard
            key={drill.drill_id ?? `${drill.priority}-${drill.name}`}
            drill={drill}
          />
        ))}
      </div>
    </section>
  );
}

export default DrillTable;
