import React, { useState } from 'react';

const ACCEPT = '.mp4,.avi,.mov,.mkv';
// Лог прогона тренажёра: KovaaK's пишет .csv в FPSAimTrainer/stats,
// Aimbeast экспортирует .csv или .json.
const STATS_ACCEPT = '.csv,.json,.txt';
// Платформы, для которых лог имеет смысл: у игрового клипа момент выстрела
// не измеряется ничем.
const TRAINER_PLATFORMS = ['kovaaks', 'aimbeast'];
// Должен совпадать с MAX_UPLOAD_MB на backend — иначе лимит встретит
// игрока только после долгой загрузки.
const MAX_MB = Number(process.env.REACT_APP_MAX_UPLOAD_MB || 300);

function UploadForm({ onSubmit, submitting, user }) {
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState(null);
  const [playerId, setPlayerId] = useState('');
  const [sens, setSens] = useState('');
  const [edpi, setEdpi] = useState('');
  const [agent, setAgent] = useState('');
  const [mapName, setMapName] = useState('');
  const [trainingPlatform, setTrainingPlatform] = useState('');
  const [steamId, setSteamId] = useState('');
  const [statsFile, setStatsFile] = useState(null);

  // Предзаполнение из аккаунта, когда /me долетел ПОСЛЕ монтирования формы.
  // Зависим только от user: правка поля игроком (steamId) переигрывать эффект
  // не должна, иначе ввод затирался бы значением аккаунта.
  const accountSteamId = user?.steam_id;
  React.useEffect(() => {
    if (accountSteamId) setSteamId((prev) => prev || accountSteamId);
  }, [accountSteamId]);

  const ready = file && playerId.trim() && !submitting;
  const showStats = TRAINER_PLATFORMS.includes(trainingPlatform);

  // Смена платформы на игровую снимает уже выбранный лог: иначе он уехал бы
  // на сервер и вернулся 422.
  React.useEffect(() => {
    if (!TRAINER_PLATFORMS.includes(trainingPlatform)) setStatsFile(null);
  }, [trainingPlatform]);

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
      steamId: steamId.trim(),
      statsFile: showStats ? statsFile : null,
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
              <option value="aimbeast">Aimbeast</option>
            </select>
          </div>
          {showStats && (
            <div className="field">
              <label htmlFor="stats-file">Файл статистики прогона</label>
              <input id="stats-file" type="file" accept={STATS_ACCEPT}
                onChange={(e) => setStatsFile(e.target.files?.[0] || null)} />
              <span className="field-hint">
                Необязательно. KovaaK&apos;s кладёт CSV в
                {' '}FPSAimTrainer/stats рядом с записью. С ним в разборе
                появятся точность и TTK — движок их по кадрам не видит.
              </span>
            </div>
          )}
          <div className="field">
            <label htmlFor="steam-id">SteamID64 (ранг KovaaK&apos;s)</label>
            <input id="steam-id" type="text" inputMode="numeric"
              pattern="\d{17}" value={steamId}
              onChange={(e) => setSteamId(e.target.value)}
              placeholder="76561198…" />
            <span className="field-hint">
              17 цифр — найти на steamid.io или в URL профиля Steam.
              Подтянем ваш ранг Voltaic S5 из KovaaK&apos;s.
            </span>
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
