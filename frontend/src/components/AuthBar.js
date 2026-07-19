import React, { useState } from 'react';
import { getLoginUrl, logout } from '../api';

/** Шапка аккаунта: mode=off — не рендерится; гость — кнопка входа;
 *  залогинен — аватар (готовый avatar_url с бэка) + ник + выход. */
function AuthBar({ mode, user, onAuthChange }) {
  const [busy, setBusy] = useState(false);

  if (mode !== 'discord') return null;

  const handleLogin = async () => {
    setBusy(true);
    try {
      const { url } = await getLoginUrl();
      window.location.assign(url);
    } catch {
      setBusy(false); // бэкенд не ответил — остаёмся гостем без падения
    }
  };

  const handleLogout = async () => {
    setBusy(true);
    try {
      await logout();
      await onAuthChange();
    } finally {
      setBusy(false);
    }
  };

  if (!user) {
    return (
      <div className="auth-bar">
        <button type="button" className="btn" onClick={handleLogin}
                disabled={busy}>
          Войти через Discord
        </button>
      </div>
    );
  }

  return (
    <div className="auth-bar">
      <img className="auth-avatar" src={user.avatar_url} alt=""
           width="28" height="28" />
      <span className="auth-name">{user.username}</span>
      <button type="button" className="btn btn-quiet" onClick={handleLogout}
              disabled={busy}>
        Выйти
      </button>
    </div>
  );
}

export default AuthBar;
