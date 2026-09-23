import { uploadClip } from './api';

// Ответы fetch по порядку вызовов; body запросов копим для проверок.
function mockFetch(...responses) {
  const calls = [];
  global.fetch = jest.fn((url, init = {}) => {
    calls.push({ url, body: init.body });
    const json = responses.shift();
    return Promise.resolve({ ok: true, status: 200, json: async () => json });
  });
  return calls;
}

const clip = new File(['v'], 'clip3.mp4', { type: 'video/mp4' });
const stats = new File(['Kill #'], 'run Stats.csv', { type: 'text/csv' });

afterEach(() => { delete global.fetch; });

test('presigned: лог тренажёра уходит в /start', async () => {
  const calls = mockFetch(
    { mode: 'presigned', upload_url: 'https://r2.example/put', key: 'uploads/k.mp4' },
    {},
    { session_id: 's1' },
  );

  await uploadClip({ file: clip, statsFile: stats, playerId: 'friend',
                     trainingPlatform: 'kovaaks' });

  const start = calls.find((c) => c.url.endsWith('/api/v1/analysis/start'));
  expect(start.body.get('stats')).toBeInstanceOf(File);
  expect(start.body.get('stats').name).toBe('run Stats.csv');
  // PUT в бакет — только сам клип
  expect(calls[1].body).toBe(clip);
});

test('presigned без лога: поле stats не отправляется', async () => {
  const calls = mockFetch(
    { mode: 'presigned', upload_url: 'https://r2.example/put', key: 'uploads/k.mp4' },
    {},
    { session_id: 's1' },
  );

  await uploadClip({ file: clip, playerId: 'friend' });

  const start = calls.find((c) => c.url.endsWith('/api/v1/analysis/start'));
  expect(start.body.has('stats')).toBe(false);
});
