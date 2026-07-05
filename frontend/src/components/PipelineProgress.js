import React from 'react';

// Станции конвейера в порядке backend-статусов.
const STEPS = [
  { key: 'PENDING', title: 'Загрузка', detail: 'клип сохраняется на сервере' },
  { key: 'DETECTING', title: 'Детекция', detail: 'YOLO ищет головы врагов на каждом кадре' },
  { key: 'MEASURING', title: 'Измерение', detail: 'движок считает смещения прицела в HU и режет эпизоды' },
  { key: 'COACHING', title: 'Разбор', detail: 'коуч объясняет числа; валидатор сверяет каждое с движком' },
];

function PipelineProgress({ status }) {
  const activeIdx = Math.max(STEPS.findIndex((s) => s.key === status), 0);

  return (
    <section className="panel progress" aria-live="polite">
      <ol className="progress-steps">
        {STEPS.map((step, idx) => {
          const state =
            idx < activeIdx ? 'done' : idx === activeIdx ? 'active' : 'ahead';
          return (
            <li key={step.key} className={`progress-step is-${state}`}>
              <span className="progress-dot" aria-hidden="true" />
              <div>
                <div className="progress-title">{step.title}</div>
                <div className="progress-detail">{step.detail}</div>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="progress-note">
        Детекция гоняет нейросеть по всем кадрам — на минутном клипе это
        занимает несколько минут. Страница обновится сама.
      </p>
    </section>
  );
}

export default PipelineProgress;
