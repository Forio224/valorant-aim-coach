import React from 'react';

const STATUS_LABELS = { COMPLETED: 'готов', FAILED: 'не удался' };

function statusInfo(status) {
  return {
    label: STATUS_LABELS[status] ?? 'в работе',
    css: status === 'COMPLETED' ? 'hit' : status === 'FAILED' ? 'miss' : 'hypo',
  };
}

/** Последние разборы владельца; клик — существующий механизм ?session=<id>
 *  (сессии «в работе» открывают экран прогресса — App это уже умеет).
 *  Пустой список — не рендерится. */
function SessionHistory({ sessions, onOpen }) {
  if (!sessions || sessions.length === 0) return null;

  return (
    <section className="panel session-history">
      <h2>Мои разборы</h2>
      <ul>
        {sessions.map((s) => {
          const { label, css } = statusInfo(s.status);
          return (
            <li key={s.session_id}>
              <button type="button" className="session-row"
                      onClick={() => onOpen(s.session_id)}>
                <span className={`session-status session-status-${css}`}>
                  {label}
                </span>
                <span className="session-player">{s.player_id}</span>
                <span className="session-clip">{s.clip_id}</span>
                <time className="session-date">
                  {new Date(s.created_at).toLocaleString('ru-RU', {
                    day: 'numeric', month: 'short',
                    hour: '2-digit', minute: '2-digit',
                  })}
                </time>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default SessionHistory;
