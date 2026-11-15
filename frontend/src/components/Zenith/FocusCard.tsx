import { useEffect, useRef, useState } from 'react';
import { Skyline } from './ZenArt';
import { lifeApi, type LifeSummary } from './lifeApi';
import { dailyQuote, ringDash, sparkline } from './zenMath';

const DAY_LETTER = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

export function FocusCard({ summary, onEnterFocus }: { summary: LifeSummary | null; onEnterFocus: () => void }) {
  const quote = dailyQuote();
  const week = summary?.week ?? [];
  const { points, path } = sparkline(week.map((d) => d.percent), 300, 70, 14);
  const today = week[week.length - 1]?.percent ?? 0;
  const avg = week.length ? Math.round(week.reduce((s, d) => s + d.percent, 0) / week.length) : 0;
  const words = quote.text.split(' ');
  const last = words.pop();

  return (
    <section className="zen-card zen-hero" id="zen-focus" aria-label="Focus">
      <Skyline scene="city" figure className="zen-hero__art" />
      <div className="zen-hero__content">
        <span className="zen-hero__mark" aria-hidden="true">“</span>
        <h2 className="zen-hero__quote">
          {words.join(' ')} <em>{last}</em>
        </h2>
        <span className="zen-muted">Keep building.</span>
        <button type="button" className="zen-cta" onClick={onEnterFocus}>
          Enter focus mode <span aria-hidden="true">›</span>
        </button>
      </div>
      <div className="zen-week">
        <header><span className="zen-eyebrow">Weekly progress</span><strong>{avg}%</strong></header>
        <svg viewBox="0 0 300 70" aria-label={`Habit completion this week, ${avg}% on average`}>
          <path d={path} className="zen-week__line" />
          {points.map((p, i) => (
            <circle key={week[i]?.day ?? i} cx={p.x} cy={p.y} r={i === points.length - 1 ? 4.5 : 3} className={i === points.length - 1 ? 'is-today' : ''} />
          ))}
        </svg>
        <div className="zen-week__days">
          {week.map((d, i) => (
            <span key={d.day} className={i === week.length - 1 ? 'is-today' : ''}>{DAY_LETTER[new Date(`${d.day}T12:00:00`).getDay()]}</span>
          ))}
        </div>
        <p className="zen-muted">{today}% of today's habits done</p>
      </div>
    </section>
  );
}

const PRESETS = [25, 50, 90];

/** Full-screen focus timer; finished (or partly finished) sessions are logged. */
export function FocusOverlay({ onClose, onLogged }: { onClose: () => void; onLogged: (minutes: number) => void }) {
  const [minutes, setMinutes] = useState(25);
  const [left, setLeft] = useState(25 * 60);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [label, setLabel] = useState('');
  const loggedRef = useRef(false);
  const total = minutes * 60;
  const elapsedMin = Math.floor((total - left) / 60);

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [running]);

  const log = async (mins: number) => {
    if (loggedRef.current || mins < 1) return;
    loggedRef.current = true;
    await lifeApi.addFocus(mins, label).catch(() => undefined);
    onLogged(mins);
  };

  useEffect(() => {
    if (left === 0 && running) {
      setRunning(false);
      setDone(true);
      void log(minutes);
    }
  }); // runs each tick; guarded by loggedRef

  const leave = async () => {
    if (!done) await log(elapsedMin);
    onClose();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') void leave(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const mm = String(Math.floor(left / 60)).padStart(2, '0');
  const ss = String(left % 60).padStart(2, '0');
  const pct = ((total - left) / total) * 100;

  return (
    <div className="zen-focus" role="dialog" aria-modal="true" aria-label="Focus mode">
      <Skyline scene="mountain" figure className="zen-focus__art" />
      <div className="zen-focus__panel">
        <span className="zen-eyebrow">Focus mode</span>
        <div className="zen-focus__ring">
          <svg viewBox="0 0 220 220" aria-hidden="true">
            <circle cx="110" cy="110" r="96" className="zen-ring__track" />
            <circle cx="110" cy="110" r="96" className="zen-ring__fill" strokeDasharray={ringDash(pct, 96)} />
          </svg>
          <div className="zen-focus__time" aria-live="off">{mm}:{ss}</div>
        </div>
        {done ? (
          <p className="zen-focus__msg">Session complete. {minutes} focused minutes logged.</p>
        ) : (
          <>
            {!running && left === total && (
              <div className="zen-row zen-focus__presets">
                {PRESETS.map((m) => (
                  <button key={m} type="button" className={`zen-btn ${m === minutes ? 'zen-btn--solid' : ''}`} onClick={() => { setMinutes(m); setLeft(m * 60); }}>
                    {m} min
                  </button>
                ))}
              </div>
            )}
            <input className="zen-focus__label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="What are you focusing on?" aria-label="Focus label" maxLength={80} />
          </>
        )}
        <div className="zen-row">
          {!done && (
            <button type="button" className="zen-btn zen-btn--solid" onClick={() => setRunning((r) => !r)}>
              {running ? 'Pause' : left === total ? 'Start' : 'Resume'}
            </button>
          )}
          <button type="button" className="zen-btn" onClick={() => void leave()}>
            {done ? 'Close' : elapsedMin >= 1 ? `End and log ${elapsedMin} min` : 'Leave'}
          </button>
        </div>
        <p className="zen-muted">{dailyQuote().text}</p>
      </div>
    </div>
  );
}
