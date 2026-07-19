import React from 'react';
import { render, screen } from '@testing-library/react';
import DrillTable from './DrillTable';

const DRILL = {
  priority: 1, drill_id: 'correction_t1_vt_pasu_novice',
  name: 'VT Pasu Novice S5', platform: 'kovaaks', tier: 1,
  dose: '3 подхода по 5 минут', target_metric: 'correction',
  rationale: 'r', success_criterion: 'критерий',
  external_score: 812, external_threshold: 800,
};

test('дрилл со скором KovaaK\'s показывает скор и порог', () => {
  render(<DrillTable drills={[DRILL]} />);
  expect(screen.getByText(/812/)).toBeInTheDocument();
  expect(screen.getByText(/800/)).toBeInTheDocument();
});

test('без внешних чисел строка скора не рендерится', () => {
  render(<DrillTable drills={[{ ...DRILL, external_score: null,
                                external_threshold: null }]} />);
  expect(screen.queryByText(/скор/i)).not.toBeInTheDocument();
});
