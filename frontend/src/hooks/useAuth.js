import { useCallback, useEffect, useState } from 'react';
import { getMe } from '../api';

/** Один запрос /auth/me при старте: режим (off|discord) + пользователь.
 *  Без глобального стора — состояние живёт в App и идёт вниз пропсами. */
export default function useAuth() {
  const [state, setState] = useState({ mode: 'off', user: null, loading: true });

  const refresh = useCallback(async () => {
    try {
      const { mode, user } = await getMe();
      setState({ mode, user, loading: false });
    } catch {
      // Бэкенд недоступен — ведём себя как аноним, форма сама покажет ошибку
      setState({ mode: 'off', user: null, loading: false });
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { ...state, refresh };
}
