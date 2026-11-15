import { useState } from 'react';
import type { Jarvis } from '../Jarvis/useJarvis';
import { Gate, Skyline } from './ZenArt';
import { IconBook, IconCheck, IconFlag, IconTarget, IconBars } from './icons';
import { lifeApi, type LifeSummary } from './lifeApi';
import { dailyQuote } from './zenMath';

const DEFAULT_STAGES = ['Discipline foundation', 'Consistency builder', 'Mindset upgrade', 'Legacy creator'];

/** Live PC status (replaces the design's card panel) plus quick actions. */
export function SystemCard({
  j,
  onAction,
}: {
  j: Jarvis;
  onAction: (action: 'habit' | 'focus' | 'journal' | 'stats' | 'goals') => void;
}) {
  const temp = j.energy.gpu_temp_c ?? j.energy.cpu_temp_c ?? null;
  const tps = j.lastTps || j.stats.avg_throughput_tok_per_sec || 0;
  const actions = [
    { id: 'habit' as const, label: 'Habit', icon: <IconCheck /> },
    { id: 'focus' as const, label: 'Focus', icon: <IconTarget /> },
    { id: 'journal' as const, label: 'Journal', icon: <IconBook /> },
    { id: 'stats' as const, label: 'Stats', icon: <IconBars /> },
    { id: 'goals' as const, label: 'Goals', icon: <IconFlag /> },
  ];
  return (
    <section className="zen-card zen-system" aria-label="System">
      <div className="zen-system__panel">
        <header>
          <span className="zen-eyebrow">System core</span>
          <span className={`zen-chip ${j.online ? 'on' : 'off'}`}>{j.online ? 'Online' : 'Offline'}</span>
        </header>
        <div className="zen-system__grid">
          <div><span>Model</span><b>{j.model === 'auto' ? 'Auto' : j.model || '—'}</b></div>
          <div><span>Speed</span><b>{tps ? `${tps.toFixed(0)} t/s` : '—'}</b></div>
          <div><span>GPU load</span><b>{j.stats.avg_gpu_utilization_pct != null ? `${Math.round(j.stats.avg_gpu_utilization_pct)}%` : '—'}</b></div>
          <div><span>Temp</span><b>{temp != null ? `${Math.round(temp)}°C` : '—'}</b></div>
        </div>
        <footer>
          <span>{(j.stats.total_requests ?? 0).toLocaleString()} requests</span>
          <span>{(j.stats.total_tokens ?? 0).toLocaleString()} tokens</span>
        </footer>
      </div>
      <span className="zen-eyebrow">Quick actions</span>
      <div className="zen-actions">
        {actions.map((a) => (
          <button key={a.id} type="button" onClick={() => onAction(a.id)}>
            <span>{a.icon}</span>
            {a.label}
          </button>
        ))}
      </div>
    </section>
  );
}

export function MissionCard({ summary, onChanged }: { summary: LifeSummary | null; onChanged: () => void }) {
  const mission = summary?.mission ?? null;
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState('Become unstoppable');
  const [stages, setStages] = useState(DEFAULT_STAGES.join('\n'));

  const save = async () => {
    await lifeApi.setMission(title, stages.split('\n')).catch(() => undefined);
    setEditing(false);
    onChanged();
  };
  const advance = async () => {
    await lifeApi.advanceMission().catch(() => undefined);
    onChanged();
  };
  const startEdit = () => {
    setTitle(mission?.title ?? 'Become unstoppable');
    setStages((mission?.stages ?? DEFAULT_STAGES).join('\n'));
    setEditing(true);
  };

  return (
    <section className="zen-card zen-mission" id="zen-mission" aria-label="Current mission">
      <Gate className="zen-mission__art" />
      <div className="zen-mission__body">
        <span className="zen-eyebrow">Current mission</span>
        {editing ? (
          <form className="zen-mission__form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            <input value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Mission" maxLength={80} />
            <textarea value={stages} onChange={(e) => setStages(e.target.value)} aria-label="Stages, one per line" rows={4} />
            <div className="zen-row">
              <button type="submit" className="zen-btn zen-btn--solid">Save mission</button>
              <button type="button" className="zen-btn" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </form>
        ) : mission ? (
          <>
            <h3>{mission.title}</h3>
            <div className="zen-bar"><i style={{ width: `${mission.percent}%` }} /><span>{mission.percent}%</span></div>
            <span className="zen-eyebrow">Mission roadmap</span>
            <ol className="zen-roadmap">
              {mission.stages.map((s, i) => (
                <li key={s} className={i < mission.stage ? 'is-done' : i === mission.stage ? 'is-current' : ''}>
                  <b>{i + 1}</b>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
            <div className="zen-row">
              <button type="button" className="zen-btn zen-btn--solid" disabled={mission.stage >= mission.stages.length} onClick={() => void advance()}>
                {mission.stage >= mission.stages.length ? 'Mission complete' : 'Complete stage'}
              </button>
              <button type="button" className="zen-btn" onClick={startEdit}>Edit roadmap</button>
            </div>
          </>
        ) : (
          <>
            <h3>Set your mission</h3>
            <p className="zen-muted">Name what you are working toward and the stages to get there.</p>
            <button type="button" className="zen-btn zen-btn--solid" onClick={startEdit}>Create roadmap</button>
          </>
        )}
      </div>
    </section>
  );
}

export function ReminderCard() {
  const q = dailyQuote(new Date(Date.now() + 86_400_000 * 3));
  return (
    <section className="zen-card zen-reminder" aria-label="Daily reminder">
      <span className="zen-eyebrow">Daily reminder</span>
      <span className="zen-hero__mark" aria-hidden="true">“</span>
      <p>{q.text}</p>
      <Skyline scene="sea" className="zen-reminder__art" />
    </section>
  );
}
