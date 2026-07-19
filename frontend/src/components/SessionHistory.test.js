import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SessionHistory from './SessionHistory';

const ROWS = [
  { session_id: 's1', status: 'COMPLETED', player_id: 'me',
    clip_id: 'ace', created_at: '2026-07-19T10:00:00+00:00' },
  { session_id: 's2', status: 'DETECTING', player_id: 'me',
    clip_id: 'fresh', created_at: '2026-07-19T11:00:00+00:00' },
];

test('пустой список — секция не рендерится', () => {
  const { container } = render(
    <SessionHistory sessions={[]} onOpen={() => {}} />,
  );
  expect(container).toBeEmptyDOMElement();
});

test('список: статусы человеком, клик отдаёт session_id', async () => {
  const onOpen = jest.fn();
  render(<SessionHistory sessions={ROWS} onOpen={onOpen} />);

  expect(screen.getByText('готов')).toBeInTheDocument();
  expect(screen.getByText('в работе')).toBeInTheDocument();

  await userEvent.click(screen.getByText('ace').closest('button'));
  expect(onOpen).toHaveBeenCalledWith('s1');
});

test('клик по строке «в работе» тоже открывает сессию (экран прогресса)', async () => {
  const onOpen = jest.fn();
  render(<SessionHistory sessions={ROWS} onOpen={onOpen} />);
  await userEvent.click(screen.getByText('в работе').closest('button'));
  expect(onOpen).toHaveBeenCalledWith('s2');
});
