import React, { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAnalysis, uploadClip } from './api';
import PipelineProgress from './components/PipelineProgress';
import UploadForm from './components/UploadForm';
import ReportView from './components/report/ReportView';
import './index.css';

const POLL_MS = 3000;
const TERMINAL = ['COMPLETED', 'FAILED'];

function App() {
  // Сессия живёт в URL (?session=...) — отчётом можно поделиться ссылкой.
  const [sessionId, setSessionId] = useState(
    () => new URLSearchParams(window.location.search).get('session'),
  );
  const [analysis, setAnalysis] = useState(null); // последний GET-ответ
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef(null);

  const status = analysis?.status ?? (sessionId ? 'PENDING' : null);
  const isRunning = Boolean(sessionId) && !TERMINAL.includes(status);

  useEffect(() => {
    if (!isRunning) return undefined;
    const tick = async () => {
      try {
        const data = await fetchAnalysis(sessionId);
        setAnalysis(data);
        if (data.status === 'FAILED') {
          setError(data.error || 'разбор прервался без объяснения');
        }
      } catch (err) {
        // Сеть мигнула — молча пробуем следующим тиком, поллинг дешёвый.
      }
    };
    tick(); // первый запрос сразу — готовый отчёт открывается без паузы
    pollRef.current = setInterval(tick, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [sessionId, isRunning]);

  const handleSubmit = useCallback(async (fields) => {
    setSubmitting(true);
    setError(null);
    setAnalysis(null);
    try {
      const { session_id: id } = await uploadClip(fields);
      window.history.replaceState(null, '', `?session=${id}`);
      setSessionId(id);
    } catch (err) {
      setError(`Не удалось загрузить клип — ${err.message}. ` +
        'Проверьте, что backend запущен на порту 8000.');
    } finally {
      setSubmitting(false);
    }
  }, []);

  const reset = useCallback(() => {
    window.history.replaceState(null, '', window.location.pathname);
    setSessionId(null);
    setAnalysis(null);
    setError(null);
  }, []);

  const showForm = !sessionId;
  const showReport = status === 'COMPLETED' && analysis;

  return (
    <div className="app">
      <header className="masthead">
        <span className="masthead-brand">Аим-паспорт</span>
        <span className="masthead-sub">разбор аима Valorant по кадрам-уликам</span>
      </header>

      <main className="page">
        {showForm && (
          <>
            <section className="hero">
              <h1>
                Каждый совет — с кадром-доказательством
              </h1>
              <p className="hero-lede">
                Детектор находит головы врагов, движок меряет смещение прицела
                в Head Units, коуч объясняет числа и собирает план тренировок.
                Числа считает только движок — коуч не имеет права их выдумывать.
              </p>
            </section>
            <UploadForm onSubmit={handleSubmit} submitting={submitting} />
          </>
        )}

        {error && (
          <div className="notice notice-miss" role="alert">
            <strong>Разбор не удался.</strong> {error}
            {sessionId && (
              <button type="button" className="btn btn-quiet" onClick={reset}>
                Попробовать другой клип
              </button>
            )}
          </div>
        )}

        {isRunning && <PipelineProgress status={status} />}

        {showReport && (
          <ReportView analysis={analysis} onReset={reset} />
        )}
      </main>

      <footer className="footer">
        <span>
          Метрики в HU (Head Units) — смещение прицела в высотах головы цели.
        </span>
      </footer>
    </div>
  );
}

export default App;
