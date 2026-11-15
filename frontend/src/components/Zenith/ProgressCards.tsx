import { useState } from 'react';
import type { Automation } from '../Hud/automationApi';
import { Crystal, Skyline } from './ZenArt';
import { IconCheck, IconClock, IconPlus } from './icons';
import { lifeApi, localDay, type Habit, type LifeSummary } from './lifeApi';
import { ringDash } from './zenMath';

const PROGRESS_ROWS: { key: keyof LifeSummary['progress']; label: string }[] = [
  { key: 'discipline', label: 'Discipline' },
  { key: 'habits', label: 'Habits' },
  { key: 'mindset', label: 'Mindset' },
  { key: 'focus', label: 'Focus' },
];

export function ProgressRingCard({ summary }: { summary: LifeSummary | null }) {
  const p = summary?.progress;
  const overall = p?.overall ?? 0;
  return (
    <section className="zen-card zen-progress" aria-label="Overall progress">
      <header className="zen-card__bar"><span className="zen-eyebrow">Overall progress</span><span className="zen-muted">This week</span></header>
      <div className="zen-progress__body">
        <div className="zen-ring">
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <circle cx="60" cy="60" r="50" className="zen-ring__track" />
            <circle cx="60" cy="60" r="50" className="zen-ring__fill" strokeDasharray={ringDash(overall, 50)} />
          </svg>
          <div className="zen-ring__label"><strong>{overall}%</strong><span>complete</span></div>
        </div>
        <ul className="zen-legend">
          {PROGRESS_ROWS.map((row) => (
            <li key={row.key}>
              <i className={`dot dot--${row.key}`} />
              <span>{row.label}</span>
              <b>{p?.[row.key] ?? 0}%</b>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

const fmtTime = (hhmm: string) => {
  if (!hhmm) return '';
  const [h, m] = hhmm.split(':').map(Number);
  return new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

/** Habits for today (tick to complete) plus routines that run today. */
export function ScheduleCard({
  summary,
  routines,
  onChanged,
  onOpenRoutines,
}: {
  summary: LifeSummary | null;
  routines: Automation[];
  onChanged: () => void;
  onOpenRoutines: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [time, setTime] = useState('');
  const [error, setError] = useState<string | null>(null);
  const habits = summary?.today.habits ?? [];
  const today = localDay();
  const todaysRoutines = routines.filter(
    (r) => r.status === 'active' && r.next_run && localDay(new Date(r.next_run)) === today,
  );

  const toggle = async (h: Habit) => {
    await lifeApi.checkHabit(h.id, !h.done).catch(() => undefined);
    onChanged();
  };
  const add = async () => {
    try {
      await lifeApi.addHabit(name, time);
      setName(''); setTime(''); setAdding(false); setError(null);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="zen-card zen-schedule" id="zen-schedule" aria-label="Today's schedule">
      <header className="zen-card__bar">
        <span className="zen-eyebrow">Today's schedule</span>
        <button type="button" className="zen-link" onClick={() => setAdding((a) => !a)}>
          <IconPlus /> Habit
        </button>
      </header>
      {adding && (
        <form className="zen-inline-form" onSubmit={(e) => { e.preventDefault(); void add(); }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New habit, e.g. Read 20 pages" aria-label="Habit name" maxLength={80} autoFocus />
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} aria-label="Time (optional)" />
          <button type="submit" className="zen-btn zen-btn--solid" disabled={!name.trim()}>Add</button>
          {error && <p className="zen-error">{error}</p>}
        </form>
      )}
      <ul className="zen-tasks">
        {habits.length === 0 && todaysRoutines.length === 0 && (
          <li className="zen-empty">No habits yet. Add one here or tell Jarvis: "add a habit to meditate at 10 pm".</li>
        )}
        {habits.map((h) => (
          <li key={h.id} className={h.done ? 'is-done' : ''}>
            <button type="button" className="zen-check" aria-pressed={h.done} aria-label={`${h.done ? 'Undo' : 'Complete'} ${h.name}`} onClick={() => void toggle(h)}>
              {h.done && <IconCheck />}
            </button>
            <span className="zen-tasks__name">{h.name}</span>
            <time>{fmtTime(h.time)}</time>
          </li>
        ))}
        {todaysRoutines.map((r) => (
          <li key={r.id} className="is-routine">
            <span className="zen-check zen-check--routine" aria-hidden="true"><IconClock /></span>
            <button type="button" className="zen-tasks__name zen-link-plain" onClick={onOpenRoutines} title="Routine run by Jarvis">{r.name}</button>
            <time>{r.next_run ? new Date(r.next_run).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</time>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function StreakCard({ summary }: { summary: LifeSummary | null }) {
  const streak = summary?.streak ?? 0;
  return (
    <section className="zen-card zen-streak" aria-label="Focus streak">
      <div>
        <span className="zen-eyebrow">Focus streak</span>
        <strong className="zen-streak__num">{streak}</strong>
        <span className="zen-streak__unit">{streak === 1 ? 'day' : 'days'}</span>
        <p className="zen-muted">{streak ? 'Keep the chain going today.' : 'Complete a habit to start a streak.'}</p>
      </div>
      <Crystal />
    </section>
  );
}

/** Kaizen: continuous improvement, the three scores that matter most. */
export function KaizenCard({ summary }: { summary: LifeSummary | null }) {
  const p = summary?.progress;
  const scores = [
    { label: 'Discipline', value: p?.discipline ?? 0 },
    { label: 'Focus', value: p?.focus ?? 0 },
    { label: 'Consistency', value: p?.habits ?? 0 },
  ];
  return (
    <section className="zen-card zen-kaizen" aria-label="Kaizen">
      <Skyline scene="mountain" figure className="zen-kaizen__art" />
      <div className="zen-kaizen__glyph" aria-hidden="true"><span>改</span><span>善</span><small>KAIZEN</small></div>
      <div className="zen-kaizen__scores">
        {scores.map((s) => (
          <div key={s.label} className="zen-score"><span>{s.label}</span><b>{s.value}</b></div>
        ))}
      </div>
      <p className="zen-kaizen__line">
        One percent better than yesterday, every day. That is how ordinary becomes <em>rare</em>.
      </p>
    </section>
  );
}
