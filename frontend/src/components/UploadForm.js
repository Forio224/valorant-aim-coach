import React, { useState } from 'react';

const ACCEPT = '.mp4,.avi,.mov,.mkv';
// Должен совпадать с MAX_UPLOAD_MB на backend — иначе лимит встретит
// игрока только после долгой загрузки.
const MAX_MB = Number(process.env.REACT_APP_MAX_UPLOAD_MB || 300);

function UploadForm({ onSubmit, submitting }) {
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState(null);
  const [playerId, setPlayerId] = useState('');
  const [sens, setSens] = useState('');
  const [edpi, setEdpi] = useState('');
  const [agent, setAgent] = useState('');
  const [mapName, setMapName] = useState('');
  const [trainingPlatform, setTrainingPlatform] = useState('');

  const ready = file && playerId.trim() && !submitting;

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!ready) return;
    onSubmit({
      file,
      playerId: playerId.trim(),
      sens: sens.trim(),
      edpi: edpi.trim(),
      agent: agent.trim(),
      mapName: mapName.trim(),
      trainingPlatform,
    });
  };

  return (
    <form className="panel upload-form" onSubmit={handleSubmit}>
      <div className="field-row">
        <label className="file-field" data-filled={file ? 'yes' : 'no'}>
          <input
            type="file"
            accept={ACCEPT}
            onChange={(e) => {
              const picked = e.target.files[0] ?? null;
              if (picked && picked.size > MAX_MB * 1048576) {
                setFile(null);
                setFileError(
                  `Файл ${(picked.size / 1048576).toFixed(0)} МБ — больше ` +
                  `лимита ${MAX_MB} МБ. Обрежьте клип до нужного боя.`,
                );
              } else {
                setFile(picked);
                setFileError(null);
              }
            }}
            disabled={submitting}
          />
          <span className="file-field-title">
            {file ? file.name : 'Выбрать клип'}
          </span>
          <span className="file-field-hint">
            {file
              ? `${(file.size / 1048576).toFixed(1)} МБ`
              : `mp4 · avi · mov · mkv · до ${MAX_MB} МБ`}
          </span>
          {fileError && <span className="file-field-error">{fileError}</span>}
        </label>

        <div className="field">
          <label htmlFor="player-id">Кто играет в клипе</label>
          <input
            id="player-id"
            type="text"
            value={playerId}
            placeholder="ник игрока"
            onChange={(e) => setPlayerId(e.target.value)}
            disabled={submitting}
            required
          />
          <span className="field-hint">
            Клипы одного игрока копятся в его профиль — не смешивайте людей.
          </span>
        </div>
      </div>

      <details className="extras">
        <summary>Сенса и матч — если хотите видеть их в отчёте</summary>
        <div className="extras-grid">
          <div className="field">
            <label htmlFor="sens">Сенса</label>
            <input id="sens" type="number" step="any" min="0" value={sens}
              onChange={(e) => setSens(e.target.value)} placeholder="0.4" />
          </div>
          <div className="field">
            <label htmlFor="edpi">eDPI</label>
            <input id="edpi" type="number" step="any" min="0" value={edpi}
              onChange={(e) => setEdpi(e.target.value)} placeholder="320" />
          </div>
          <div className="field">
            <label htmlFor="agent">Агент</label>
            <input id="agent" type="text" value={agent}
              onChange={(e) => setAgent(e.target.value)} placeholder="Jett" />
          </div>
          <div className="field">
            <label htmlFor="map">Карта</label>
            <input id="map" type="text" value={mapName}
              onChange={(e) => setMapName(e.target.value)} placeholder="Ascent" />
          </div>
          <div className="field">
            <label htmlFor="training-platform">Тренировки</label>
            <select id="training-platform" value={trainingPlatform}
              onChange={(e) => setTrainingPlatform(e.target.value)}>
              <option value="">не указано</option>
              <option value="ingame">в Valorant (Range/DM)</option>
              <option value="kovaaks">KovaaK&apos;s</option>
            </select>
          </div>
        </div>
        <p className="extras-note">
          Видео не видит вашу мышь и сенсу — эти поля попадают в отчёт
          только как ваши собственные данные.
        </p>
      </details>

      <button type="submit" className="btn btn-primary" disabled={!ready}>
        {submitting ? 'Загружается…' : 'Отправить на разбор'}
      </button>
    </form>
  );
}

export default UploadForm;
