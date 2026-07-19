import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ShareButton from './ShareButton';
import * as api from '../../api';

jest.mock('../../api');

const OWNED = { id: 'abc', is_owner: true, share_token: 'tok123' };

function mockClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText }, configurable: true,
  });
}

test('гость (is_owner=false) — кнопки нет', () => {
  const { container } = render(
    <ShareButton analysis={{ id: 'abc', is_owner: false }} />,
  );
  expect(container).toBeEmptyDOMElement();
});

test('токен уже в GET — ссылка строится без POST /share', async () => {
  const writeText = jest.fn().mockResolvedValue();
  mockClipboard(writeText);

  render(<ShareButton analysis={OWNED} />);
  await userEvent.click(screen.getByRole('button', { name: /поделиться/i }));

  await screen.findByText(/ссылка скопирована/i);
  expect(api.createShareLink).not.toHaveBeenCalled();
  expect(writeText).toHaveBeenCalledWith(
    expect.stringContaining('session=abc&share=tok123'),
  );
});

test('токена нет — POST /share, затем копирование', async () => {
  const writeText = jest.fn().mockResolvedValue();
  mockClipboard(writeText);
  api.createShareLink.mockResolvedValue({ share_token: 'fresh' });

  render(<ShareButton analysis={{ id: 'abc', is_owner: true,
                                  share_token: null }} />);
  await userEvent.click(screen.getByRole('button', { name: /поделиться/i }));

  await screen.findByText(/ссылка скопирована/i);
  expect(api.createShareLink).toHaveBeenCalledWith('abc');
  expect(writeText).toHaveBeenCalledWith(
    expect.stringContaining('share=fresh'),
  );
});

test('clipboard сломан (HTTP-прод) — фолбэк: ссылка текстом', async () => {
  mockClipboard(jest.fn().mockRejectedValue(new Error('no https')));

  render(<ShareButton analysis={OWNED} />);
  await userEvent.click(screen.getByRole('button', { name: /поделиться/i }));

  await screen.findByText(/скопируйте ссылку вручную/i);
  expect(screen.getByRole('textbox').value).toContain('share=tok123');
});
