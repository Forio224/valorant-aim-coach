import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AuthBar from './AuthBar';
import * as api from '../api';

jest.mock('../api');

const USER = { id: 'u1', username: 'shooter', avatar_url: 'https://cdn/x.png' };

test('mode=off — не рендерится вовсе', () => {
  const { container } = render(
    <AuthBar mode="off" user={null} onAuthChange={() => {}} />,
  );
  expect(container).toBeEmptyDOMElement();
});

test('гость — кнопка входа ведёт на url из /auth/login', async () => {
  api.getLoginUrl.mockResolvedValue({ url: 'https://discord.com/oauth' });
  const assign = jest.fn();
  jest.spyOn(window, 'location', 'get').mockReturnValue({ assign });

  render(<AuthBar mode="discord" user={null} onAuthChange={() => {}} />);
  await userEvent.click(
    screen.getByRole('button', { name: /войти через discord/i }),
  );

  await waitFor(() => expect(assign).toHaveBeenCalledWith(
    'https://discord.com/oauth',
  ));
});

test('залогинен — аватар из avatar_url, ник и выход', async () => {
  api.logout.mockResolvedValue({ ok: true });
  const onAuthChange = jest.fn();

  render(<AuthBar mode="discord" user={USER} onAuthChange={onAuthChange} />);
  expect(screen.getByText('shooter')).toBeInTheDocument();
  expect(document.querySelector('.auth-avatar'))
    .toHaveAttribute('src', USER.avatar_url);

  await userEvent.click(screen.getByRole('button', { name: /выйти/i }));
  await waitFor(() => expect(api.logout).toHaveBeenCalled());
  expect(onAuthChange).toHaveBeenCalled();
});
