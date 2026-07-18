// Тонкий клиент API: один источник правды для адреса backend.
export const API_BASE =
  process.env.REACT_APP_API_BASE || 'http://localhost:8000';

export async function uploadClip({
  file, playerId, sens, edpi, agent, mapName, trainingPlatform,
}) {
  const form = new FormData();
  form.append('file', file);
  form.append('player_id', playerId);
  if (sens) form.append('sens', sens);
  if (edpi) form.append('edpi', edpi);
  if (agent) form.append('agent', agent);
  if (mapName) form.append('map_name', mapName);
  if (trainingPlatform) form.append('training_platform', trainingPlatform);

  const resp = await fetch(`${API_BASE}/api/v1/analysis/upload`, {
    method: 'POST',
    body: form,
  });
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '');
    throw new Error(`сервер ответил ${resp.status}${detail ? `: ${detail}` : ''}`);
  }
  return resp.json();
}

export async function fetchAnalysis(sessionId) {
  const resp = await fetch(`${API_BASE}/api/v1/analysis/${sessionId}`);
  if (!resp.ok) {
    throw new Error(`сервер ответил ${resp.status}`);
  }
  return resp.json();
}

/** "/evidence/.../frame_000177.jpg" -> 177 (номер кадра-улики). */
export function frameNumberFromUrl(url) {
  const match = /frame_(\d+)\.jpg$/.exec(url);
  return match ? parseInt(match[1], 10) : null;
}

/** Абсолютный URL кадра-улики для <img src>. */
export function evidenceSrc(url) {
  return `${API_BASE}${url}`;
}
