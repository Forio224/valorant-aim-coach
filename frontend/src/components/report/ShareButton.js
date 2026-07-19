import React, { useState } from 'react';
import { createShareLink } from '../../api';

/** «Поделиться» — только владельцу. share_token из GET используется сразу
 *  (без запроса); POST /share — лишь когда токена ещё нет. Clipboard API
 *  требует HTTPS — при сбое копирования показываем ссылку текстом. */
function ShareButton({ analysis }) {
  const [state, setState] = useState({ phase: 'idle' });

  if (!analysis.is_owner) return null;

  const handleShare = async () => {
    setState({ phase: 'busy' });
    try {
      let token = analysis.share_token;
      if (!token) {
        token = (await createShareLink(analysis.id)).share_token;
      }
      const link = `${window.location.origin}${window.location.pathname}` +
        `?session=${analysis.id}&share=${token}`;
      try {
        await navigator.clipboard.writeText(link);
        setState({ phase: 'copied' });
      } catch {
        setState({ phase: 'manual', link });
      }
    } catch {
      setState({ phase: 'error' });
    }
  };

  return (
    <div className="share">
      <button type="button" className="btn btn-quiet" onClick={handleShare}
              disabled={state.phase === 'busy'}>
        Поделиться
      </button>
      {state.phase === 'copied' && (
        <span className="share-toast" role="status">Ссылка скопирована</span>
      )}
      {state.phase === 'manual' && (
        <span className="share-manual" role="status">
          Скопируйте ссылку вручную:{' '}
          <input readOnly value={state.link}
                 onFocus={(e) => e.target.select()} />
        </span>
      )}
      {state.phase === 'error' && (
        <span className="share-toast" role="alert">
          Не удалось создать ссылку
        </span>
      )}
    </div>
  );
}

export default ShareButton;
