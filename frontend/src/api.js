// Тонкий клиент API: один источник правды для адреса backend.
export const API_BASE =
  process.env.REACT_APP_API_BASE || 'http://localhost:8000';

async function throwHttpError(resp) {
  const detail = await resp.text().catch(() => '');
  throw new Error(`сервер ответил ${resp.status}${detail ? `: ${detail}` : ''}`);
}

function metaForm({ playerId, sens, edpi, agent, mapName, trainingPlatform }) {
  const form = new FormData();
  form.append('player_id', playerId);
  if (sens) form.append('sens', sens);
  if (edpi) form.append('edpi', edpi);
  if (agent) form.append('agent', agent);
  if (mapName) form.append('map_name', mapName);
  if (trainingPlatform) form.append('training_platform', trainingPlatform);
  return form;
}

/** Прямая загрузка через API (local-хранилище / dev). */
async function uploadDirect({ file, ...meta }) {
  const form = metaForm(meta);
  form.append('file', file);
  const resp = await fetch(`${API_BASE}/api/v1/analysis/upload`, {
    method: 'POST',
    body: form,
  });
  if (!resp.ok) await throwHttpError(resp);
  return resp.json();
}

/** Presigned-загрузка (R2): PUT в бакет мимо API, затем /start. */
async function uploadPresigned({ file, ...meta }, presign) {
  const put = await fetch(presign.upload_url, { method: 'PUT', body: file });
  if (!put.ok) {
    throw new Error(`хранилище ответило ${put.status} при загрузке клипа`);
  }
  const form = metaForm(meta);
  form.append('key', presign.key);
  form.append('filename', file.name);
  const resp = await fetch(`${API_BASE}/api/v1/analysis/start`, {
    method: 'POST',
    body: form,
  });
  if (!resp.ok) await throwHttpError(resp);
  return resp.json();
}

export async function uploadClip(params) {
  const presignResp = await fetch(`${API_BASE}/api/v1/analysis/uploads`, {
    method: 'POST',
    body: (() => {
      const form = new FormData();
      form.append('filename', params.file.name);
      return form;
    })(),
  });
  if (!presignResp.ok) await throwHttpError(presignResp);
  const presign = await presignResp.json();

  if (presign.mode === 'presigned') {
    return uploadPresigned(params, presign);
  }
  return uploadDirect(params);
}

export async function fetchAnalysis(sessionId) {
  const resp = await fetch(`${API_BASE}/api/v1/analysis/${sessionId}`);
  if (!resp.ok) {
    throw new Error(`сервер ответил ${resp.status}`);
  }
  return resp.json();
}

/** "/evidence/.../frame_000177.jpg" (и presigned-URL с query) -> 177. */
export function frameNumberFromUrl(url) {
  const match = /frame_(\d+)\.jpg(?:\?|$)/.exec(url);
  return match ? parseInt(match[1], 10) : null;
}

/** Абсолютный URL кадра-улики для <img src>.
 *  R2 отдаёт готовые https-ссылки; local — путь относительно API. */
export function evidenceSrc(url) {
  return /^https?:\/\//.test(url) ? url : `${API_BASE}${url}`;
}
