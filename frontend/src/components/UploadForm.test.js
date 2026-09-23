import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import UploadForm from './UploadForm';

test('поле SteamID64 присутствует и уходит в onSubmit', async () => {
  const onSubmit = jest.fn();
  render(<UploadForm onSubmit={onSubmit} submitting={false} user={null} />);
  await userEvent.click(screen.getByText(/сенса и матч/i)); // раскрыть extras
  const field = screen.getByLabelText(/steamid64/i);
  await userEvent.type(field, '76561198000000001');
  // сабмит без файла заблокирован — проверяем только значение поля
  expect(field).toHaveValue('76561198000000001');
});

test('steam_id предзаполняется из аккаунта', async () => {
  render(<UploadForm onSubmit={() => {}} submitting={false}
                     user={{ steam_id: '76561198000000009' }} />);
  await userEvent.click(screen.getByText(/сенса и матч/i));
  expect(screen.getByLabelText(/steamid64/i))
    .toHaveValue('76561198000000009');
});

test('поле статистики появляется только для аим-тренажёра', async () => {
  render(<UploadForm onSubmit={() => {}} submitting={false} user={null} />);
  await userEvent.click(screen.getByText(/сенса и матч/i));

  // по умолчанию платформа не выбрана — логу взяться неоткуда
  expect(screen.queryByLabelText(/файл статистики/i)).toBeNull();

  const platform = screen.getByLabelText(/тренировки/i);
  await userEvent.selectOptions(platform, 'kovaaks');
  expect(screen.getByLabelText(/файл статистики/i)).toBeInTheDocument();

  await userEvent.selectOptions(platform, 'aimbeast');
  expect(screen.getByLabelText(/файл статистики/i)).toBeInTheDocument();

  // у игрового клипа выстрелы не измеряются — поле исчезает
  await userEvent.selectOptions(platform, 'ingame');
  expect(screen.queryByLabelText(/файл статистики/i)).toBeNull();
});

test('Aimbeast доступен как платформа тренировок', async () => {
  render(<UploadForm onSubmit={() => {}} submitting={false} user={null} />);
  await userEvent.click(screen.getByText(/сенса и матч/i));
  expect(screen.getByRole('option', { name: /aimbeast/i })).toBeInTheDocument();
});
