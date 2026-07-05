import React from 'react';
import { evidenceSrc } from '../../api';

/** Кликабельная улика: открывается на весь экран через onOpen. */
function EvidenceThumb({ frame, onOpen }) {
  const { url, number, note } = frame;
  const alt = note ? `Кадр ${number}: ${note}` : `Кадр-улика ${number}`;
  return (
    <figure className="evidence">
      <button
        type="button"
        className="evidence-zoom"
        onClick={() => onOpen(frame)}
        aria-label={`Открыть кадр ${number} на весь экран`}
      >
        <img
          src={evidenceSrc(url)}
          alt={alt}
          loading="lazy"
          width="1920"
          height="1080"
        />
      </button>
      <figcaption>
        <span className="evidence-no">кадр {number} · нажмите, чтобы увеличить</span>
        {note && <span className="evidence-note">{note}</span>}
      </figcaption>
    </figure>
  );
}

export default EvidenceThumb;
