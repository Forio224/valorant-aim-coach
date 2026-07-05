import React, { useEffect } from 'react';
import { evidenceSrc } from '../../api';

/** Полноэкранный просмотр улики: клик мимо кадра или Esc — закрыть. */
function Lightbox({ frame, onClose }) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  if (!frame) return null;
  const { url, number, note } = frame;

  return (
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`Кадр ${number} крупно`}
      onClick={onClose}
    >
      <figure onClick={(event) => event.stopPropagation()}>
        <img src={evidenceSrc(url)} alt={note ?? `Кадр-улика ${number}`} />
        <figcaption>
          <span className="evidence-no">кадр {number}</span>
          {note && <span className="evidence-note">{note}</span>}
        </figcaption>
      </figure>
      <button
        type="button"
        className="lightbox-close"
        onClick={onClose}
        aria-label="Закрыть"
      >
        ✕
      </button>
    </div>
  );
}

export default Lightbox;
