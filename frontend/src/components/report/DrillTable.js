import React from 'react';
import { METRIC_TITLES, PLATFORM_LABELS } from './labels';

function DrillTable({ drills }) {
  const ordered = [...drills].sort((a, b) => a.priority - b.priority);

  return (
    <section className="panel drills">
      <h2>План тренировок</h2>
      <p className="section-lede">
        По одному дриллу на проблему, в порядке приоритета. Критерий успеха —
        это когда дрилл можно бросать.
      </p>
      <div className="drills-scroll">
        <table>
          <thead>
            <tr>
              <th aria-label="Приоритет" />
              <th>Дрилл</th>
              <th>Где</th>
              <th>Дозировка</th>
              <th>Лечит</th>
              <th>Критерий успеха</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((drill) => (
              <tr key={drill.drill_id ?? `${drill.priority}-${drill.name}`}>
                <td className="drill-priority">{drill.priority}</td>
                <td className="drill-name">
                  {drill.name}
                  {drill.tier != null && (
                    <span className="chip chip-tier">tier {drill.tier}</span>
                  )}
                  {drill.rationale && (
                    <div className="drill-rationale">{drill.rationale}</div>
                  )}
                </td>
                <td>
                  <span className={`chip chip-${drill.platform}`}>
                    {PLATFORM_LABELS[drill.platform] ?? drill.platform}
                  </span>
                </td>
                <td className="drill-dose">{drill.dose}</td>
                <td className="drill-target">
                  {METRIC_TITLES[drill.target_metric] ?? drill.target_metric}
                </td>
                <td className="drill-criterion">{drill.success_criterion}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default DrillTable;
