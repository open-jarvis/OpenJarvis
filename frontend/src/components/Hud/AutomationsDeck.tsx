import { useEffect, useState } from 'react';
import {
  automationApi,
  browserTimezone,
  type Automation,
  type AutomationRun,
  type AutomationStatus,
} from './automationApi';

type Preset = 'daily' | 'weekdays' | 'weekly' | 'minutes' | 'hours' | 'once' | 'cron';

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const TEMPLATES: { name: string; prompt: string; preset: Preset; time?: string; every?: number }[] = [
  {
    name: 'Morning briefing',
    prompt:
      "Give me a short morning briefing: today's date, my PC's status, and one useful tip for the day. Keep it under 80 words.",
    preset: 'daily',
    time: '08:00',
  },
  {
    name: 'PC health check',
    prompt:
      'Check my PC status. If memory use is above 85% or free disk space is under 15 GB, say so clearly with a suggestion; otherwise reply "All systems nominal."',
    preset: 'hours',
    every: 3,
  },
  {
    name: 'Evening wrap-up',
    prompt: 'Write a two-sentence evening wrap-up reminding me to plan tomorrow and rest well.',
    preset: 'daily',
    time: '21:00',
  },
];

function buildSchedule(
  preset: Preset,
  time: string,
  day: number,
  every: number,
  onceAt: string,
  cron: string,
): { schedule_type: string; schedule_value: string } {
  const [h, m] = (time || '08:00').split(':').map((n) => parseInt(n, 10) || 0);
  switch (preset) {
    case 'daily':
      return { schedule_type: 'cron', schedule_value: `${m} ${h} * * *` };
    case 'weekdays':
      return { schedule_type: 'cron', schedule_value: `${m} ${h} * * 1-5` };
    case 'weekly':
      return { schedule_type: 'cron', schedule_value: `${m} ${h} * * ${day}` };
    case 'minutes':
      return { schedule_type: 'interval', schedule_value: String(Math.max(1, every) * 60) };
    case 'hours':
      return { schedule_type: 'interval', schedule_value: String(Math.max(1, every) * 3600) };
    case 'once':
      return {
        schedule_type: 'once',
        schedule_value: onceAt ? new Date(onceAt).toISOString() : '',
      };
    default:
      return { schedule_type: 'cron', schedule_value: cron.trim() };
  }
}

const pad = (n: number) => String(n).padStart(2, '0');

export function describeSchedule(a: Pick<Automation, 'schedule_type' | 'schedule_value'>): string {
  if (a.schedule_type === 'interval') {
    const s = Number(a.schedule_value);
    if (s % 3600 === 0) return `Every ${s / 3600 === 1 ? 'hour' : `${s / 3600} hours`}`;
    if (s % 60 === 0) return `Every ${s / 60 === 1 ? 'minute' : `${s / 60} minutes`}`;
    return `Every ${s}s`;
  }
  if (a.schedule_type === 'once') {
    const d = new Date(a.schedule_value);
    return isNaN(d.getTime()) ? `Once: ${a.schedule_value}` : `Once on ${d.toLocaleString()}`;
  }
  const parts = a.schedule_value.trim().split(/\s+/);
  if (parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1]) && parts[2] === '*' && parts[3] === '*') {
    const t = `${pad(+parts[1])}:${pad(+parts[0])}`;
    if (parts[4] === '*') return `Daily at ${t}`;
    if (parts[4] === '1-5') return `Weekdays at ${t}`;
    if (/^[0-6]$/.test(parts[4])) return `${DAYS[+parts[4]]}s at ${t}`;
  }
  return `Cron: ${a.schedule_value}`;
}

const fmtWhen = (iso: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? `Today ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}`
    : d.toLocaleString([], { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
};

function StatusPill({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <div className={`deck-pill ${ok ? 'ok' : 'off'}`} title={detail}>
      <span className="deck-pill__dot" />
      <div>
        <strong>{label}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

export function AutomationsDeck({
  open,
  onClose,
  status,
  items,
  error,
  refresh,
  onLog,
}: {
  open: boolean;
  onClose: () => void;
  status: AutomationStatus | null;
  items: Automation[];
  error: string | null;
  refresh: () => Promise<void>;
  onLog: (text: string, level?: 'info' | 'ok' | 'warn' | 'err') => void;
}) {
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [preset, setPreset] = useState<Preset>('daily');
  const [time, setTime] = useState('08:00');
  const [day, setDay] = useState(1);
  const [every, setEvery] = useState(30);
  const [onceAt, setOnceAt] = useState('');
  const [cron, setCron] = useState('0 8 * * *');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [history, setHistory] = useState<AutomationRun[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!expanded) return;
    automationApi.runs(expanded).then((r) => setHistory(r.runs)).catch(() => setHistory([]));
  }, [expanded, items]);

  if (!open) return null;

  const applyTemplate = (t: (typeof TEMPLATES)[number]) => {
    setName(t.name);
    setPrompt(t.prompt);
    setPreset(t.preset);
    if (t.time) setTime(t.time);
    if (t.every) setEvery(t.every);
    setFormError(null);
  };

  const create = async () => {
    setFormError(null);
    if (!prompt.trim()) { setFormError('Tell Jarvis what to do.'); return; }
    const sched = buildSchedule(preset, time, day, every, onceAt, cron);
    if (!sched.schedule_value) { setFormError('Pick when it should run.'); return; }
    setSaving(true);
    try {
      const created = await automationApi.create({
        name: name.trim(),
        prompt: prompt.trim(),
        ...sched,
        timezone: browserTimezone(),
      });
      onLog(`Routine "${created.name}" scheduled · ${describeSchedule(created)}`, 'ok');
      setName('');
      setPrompt('');
      await refresh();
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const act = async (a: Automation, action: 'run' | 'pause' | 'resume' | 'delete') => {
    setBusyId(a.id);
    try {
      if (action === 'run') { await automationApi.runNow(a.id); onLog(`Running "${a.name}" now…`); }
      if (action === 'pause') { await automationApi.pause(a.id); onLog(`Paused "${a.name}"`, 'warn'); }
      if (action === 'resume') { await automationApi.resume(a.id); onLog(`Resumed "${a.name}"`, 'ok'); }
      if (action === 'delete') {
        if (!window.confirm(`Delete the routine "${a.name}"?`)) return;
        await automationApi.remove(a.id);
        onLog(`Deleted "${a.name}"`, 'warn');
      }
      await refresh();
    } catch (e) {
      onLog(`Could not ${action} "${a.name}": ${(e as Error).message}`, 'err');
    } finally {
      setBusyId(null);
    }
  };

  const schedulerOff = status !== null && !status.scheduler_running;

  return (
    <div className="deck" role="dialog" aria-modal="true" aria-label="Automations">
      <div className="deck__backdrop" onClick={onClose} />
      <div className="deck__panel">
        <header className="deck__head">
          <div>
            <h2>AUTOMATION GRID</h2>
            <span>Routines Jarvis runs on its own · {status?.timezone || browserTimezone() || 'UTC'}</span>
          </div>
          <button type="button" className="hud-btn hud-btn--ghost" onClick={onClose}>CLOSE</button>
        </header>

        <div className="deck__status">
          <StatusPill
            ok={!!status?.scheduler_running}
            label="Scheduler"
            detail={status ? (status.scheduler_running ? 'Running' : 'Off — enable [scheduler] in config') : 'Checking…'}
          />
          <StatusPill
            ok={!!status?.claude.available}
            label="Claude"
            detail={
              !status ? 'Checking…'
                : status.claude.available ? `${status.claude.model} · smart routing on`
                  : status.claude.key_set ? 'Key set — restart Jarvis' : 'Needs ANTHROPIC_API_KEY'
            }
          />
          <StatusPill
            ok={!!status?.claude_code.ready}
            label="Claude Code"
            detail={status ? (status.claude_code.ready ? 'Ready for coding tasks' : status.claude_code.reason) : 'Checking…'}
          />
          <StatusPill
            ok={!!status && status.agent_tools.includes('open_app')}
            label="PC actions"
            detail={
              status
                ? status.agent_tools.includes('open_app') ? 'Enabled · risky actions need approval' : 'Tools not enabled in config'
                : 'Checking…'
            }
          />
        </div>

        {error && <p className="deck__error">Automation service: {error}</p>}

        <div className="deck__grid">
          <section className="deck__card">
            <h3>New routine</h3>
            <div className="deck__templates">
              {TEMPLATES.map((t) => (
                <button key={t.name} type="button" className="hud-chip" onClick={() => applyTemplate(t)}>
                  <span className="hud-chip__dot" />{t.name}
                </button>
              ))}
            </div>
            <label className="deck__field">
              <span>Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Morning briefing" maxLength={80} />
            </label>
            <label className="deck__field">
              <span>What should Jarvis do?</span>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                placeholder="Summarise my PC status and give me one tip for the day."
              />
            </label>
            <div className="deck__row">
              <label className="deck__field">
                <span>When</span>
                <select value={preset} onChange={(e) => setPreset(e.target.value as Preset)}>
                  <option value="daily">Every day</option>
                  <option value="weekdays">Weekdays</option>
                  <option value="weekly">Once a week</option>
                  <option value="hours">Every N hours</option>
                  <option value="minutes">Every N minutes</option>
                  <option value="once">Once</option>
                  <option value="cron">Custom (cron)</option>
                </select>
              </label>
              {(preset === 'daily' || preset === 'weekdays' || preset === 'weekly') && (
                <label className="deck__field">
                  <span>At</span>
                  <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
                </label>
              )}
              {preset === 'weekly' && (
                <label className="deck__field">
                  <span>Day</span>
                  <select value={day} onChange={(e) => setDay(+e.target.value)}>
                    {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                  </select>
                </label>
              )}
              {(preset === 'hours' || preset === 'minutes') && (
                <label className="deck__field">
                  <span>{preset === 'hours' ? 'Hours' : 'Minutes'}</span>
                  <input
                    type="number"
                    min={1}
                    max={preset === 'hours' ? 168 : 1440}
                    value={every}
                    onChange={(e) => setEvery(Math.max(1, +e.target.value || 1))}
                  />
                </label>
              )}
              {preset === 'once' && (
                <label className="deck__field">
                  <span>Date & time</span>
                  <input type="datetime-local" value={onceAt} onChange={(e) => setOnceAt(e.target.value)} />
                </label>
              )}
              {preset === 'cron' && (
                <label className="deck__field">
                  <span>Cron</span>
                  <input value={cron} onChange={(e) => setCron(e.target.value)} placeholder="0 8 * * *" />
                </label>
              )}
            </div>
            {formError && <p className="deck__error">{formError}</p>}
            <button type="button" className="hud-btn" onClick={create} disabled={saving || schedulerOff}>
              {saving ? 'SCHEDULING…' : 'SCHEDULE ROUTINE'}
            </button>
            <p className="deck__hint">
              Tip: you can also just say it — “every weekday at 9am, give me a briefing”.
            </p>
          </section>

          <section className="deck__card deck__list">
            <h3>Routines <small>{items.length}</small></h3>
            {items.length === 0 && (
              <p className="hud-muted">No routines yet. Pick a template or create one.</p>
            )}
            {items.map((a) => (
              <article key={a.id} className={`deck-item ${a.status !== 'active' ? 'is-paused' : ''}`}>
                <div className="deck-item__top">
                  <button
                    type="button"
                    className="deck-item__name"
                    onClick={() => setExpanded(expanded === a.id ? null : a.id)}
                    aria-expanded={expanded === a.id}
                  >
                    {a.name}
                  </button>
                  <span className={`deck-item__status st-${a.status}`}>{a.status.toUpperCase()}</span>
                </div>
                <div className="deck-item__meta">
                  <span>{describeSchedule(a)}</span>
                  <span>Next: {a.status === 'active' ? fmtWhen(a.next_run) : '—'}</span>
                </div>
                {a.last_result && (
                  <p className={`deck-item__result ${a.last_result.success ? 'ok' : 'err'}`}>
                    {a.last_result.success ? '✓ ' : '✕ '}
                    {a.last_result.success ? a.last_result.result || '(no output)' : a.last_result.error}
                  </p>
                )}
                <div className="deck-item__actions">
                  <button type="button" disabled={busyId === a.id} onClick={() => act(a, 'run')}>RUN NOW</button>
                  {a.status === 'active' ? (
                    <button type="button" disabled={busyId === a.id} onClick={() => act(a, 'pause')}>PAUSE</button>
                  ) : a.status === 'paused' ? (
                    <button type="button" disabled={busyId === a.id} onClick={() => act(a, 'resume')}>RESUME</button>
                  ) : null}
                  <button type="button" className="danger" disabled={busyId === a.id} onClick={() => act(a, 'delete')}>DELETE</button>
                </div>
                {expanded === a.id && (
                  <div className="deck-item__history">
                    <p className="deck-item__prompt">{a.prompt}</p>
                    {history.length === 0 ? (
                      <p className="hud-muted">No runs yet.</p>
                    ) : (
                      <ol>
                        {history.map((r) => (
                          <li key={r.id} className={r.success ? 'ok' : 'err'}>
                            <time>{fmtWhen(r.finished_at)}</time>
                            <span>{r.success ? r.result || '(no output)' : r.error}</span>
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}
              </article>
            ))}
          </section>
        </div>
      </div>
    </div>
  );
}
