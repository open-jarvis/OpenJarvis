import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle, ChevronRight, Clock, Shield } from 'lucide-react';
import {
  fetchCanonicalTasks,
  fetchCodexRuntimeHealth,
  fetchTaskTimeline,
} from '../lib/api';
import type {
  CanonicalTask,
  CanonicalTaskEvent,
  CodexRuntimeHealth,
} from '../lib/api';

const STATUS_COLORS: Record<string, string> = {
  pending: 'var(--color-text-secondary)',
  running: 'var(--color-accent)',
  waiting_approval: 'var(--color-warning)',
  paused: 'var(--color-warning)',
  recovering: 'var(--color-warning)',
  failed: 'var(--color-error)',
  done: 'var(--color-success)',
  canceled: 'var(--color-text-secondary)',
};

function shortTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function CodexTasksPanel() {
  const [tasks, setTasks] = useState<CanonicalTask[]>([]);
  const [health, setHealth] = useState<CodexRuntimeHealth | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [events, setEvents] = useState<CanonicalTaskEvent[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextTasks, nextHealth] = await Promise.all([
        fetchCanonicalTasks(),
        fetchCodexRuntimeHealth(),
      ]);
      setTasks(nextTasks);
      setHealth(nextHealth);
      setAvailable(true);
      setSelectedId(current =>
        current && nextTasks.some(task => task.task_id === current)
          ? current
          : nextTasks[0]?.task_id ?? null,
      );
    } catch {
      setAvailable(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setEvents([]);
      return;
    }
    let active = true;
    const load = async () => {
      try {
        const next = await fetchTaskTimeline(selectedId);
        if (active) setEvents(next);
      } catch {
        if (active) setEvents([]);
      }
    };
    load();
    const timer = setInterval(load, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedId]);

  if (available !== true || !health) return null;

  const selected = tasks.find(task => task.task_id === selectedId) ?? null;

  return (
    <section
      className="mb-6 rounded-xl overflow-hidden"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div
        className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2">
          <Activity size={15} style={{ color: 'var(--color-accent)' }} />
          <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            Codex task timeline
          </h2>
          <span className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
            {tasks.length} task{tasks.length === 1 ? '' : 's'}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span
            className="flex items-center gap-1 px-2 py-1 rounded-full"
            style={{
              color: health.degraded ? 'var(--color-warning)' : 'var(--color-success)',
              background: health.degraded
                ? 'color-mix(in srgb, var(--color-warning) 10%, transparent)'
                : 'color-mix(in srgb, var(--color-success) 10%, transparent)',
            }}
          >
            {health.degraded ? <AlertTriangle size={11} /> : <CheckCircle size={11} />}
            {health.active_backend || 'No backend'}
          </span>
          <span className="flex items-center gap-1" style={{ color: 'var(--color-text-secondary)' }}>
            <Shield size={11} />
            {health.sandbox} · {health.approval_mode}
          </span>
          {health.open_approvals > 0 && (
            <span style={{ color: 'var(--color-warning)' }}>
              {health.open_approvals} approval{health.open_approvals === 1 ? '' : 's'}
            </span>
          )}
        </div>
      </div>

      {tasks.length === 0 ? (
        <div className="px-4 py-8 text-sm text-center" style={{ color: 'var(--color-text-tertiary)' }}>
          No canonical Codex tasks yet.
        </div>
      ) : (
        <div className="grid md:grid-cols-[minmax(220px,0.8fr)_minmax(320px,1.4fr)] min-h-[220px]">
          <div style={{ borderRight: '1px solid var(--color-border)' }}>
            {tasks.slice(0, 20).map(task => {
              const color = STATUS_COLORS[task.status] || 'var(--color-text-secondary)';
              return (
                <button
                  key={task.task_id}
                  onClick={() => setSelectedId(task.task_id)}
                  className="w-full text-left px-4 py-3 flex items-start gap-2 cursor-pointer"
                  style={{
                    borderBottom: '1px solid var(--color-border)',
                    background: selectedId === task.task_id ? 'var(--color-bg-tertiary)' : 'transparent',
                  }}
                >
                  <span className="w-2 h-2 rounded-full mt-1.5 shrink-0" style={{ background: color }} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs truncate" style={{ color: 'var(--color-text)' }}>
                      {task.description}
                    </span>
                    <span className="block text-[10px] mt-1" style={{ color }}>
                      {task.status.replace('_', ' ')} · risk {task.risk_level}
                    </span>
                  </span>
                  <ChevronRight size={12} style={{ color: 'var(--color-text-tertiary)' }} />
                </button>
              );
            })}
          </div>

          <div className="px-4 py-3 overflow-y-auto max-h-[360px]">
            {selected && (
              <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
                <span>{selected.execution_lane}</span>
                <span>Thread {selected.active_thread_id || 'not started'}</span>
                {selected.outcome && <span>Outcome {selected.outcome}</span>}
              </div>
            )}
            <div className="space-y-2">
              {events.map(event => (
                <div key={event.event_id} className="grid grid-cols-[64px_1fr] gap-2 text-xs">
                  <span className="flex items-start gap-1" style={{ color: 'var(--color-text-tertiary)' }}>
                    <Clock size={10} className="mt-0.5" />
                    {shortTime(event.occurred_at)}
                  </span>
                  <div>
                    <div className="font-mono" style={{ color: 'var(--color-text)' }}>
                      #{event.sequence} {event.event_type}
                    </div>
                    <div className="mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                      {event.status_from && event.status_to
                        ? `${event.status_from} → ${event.status_to}`
                        : event.cause}
                    </div>
                  </div>
                </div>
              ))}
              {events.length === 0 && (
                <div className="py-8 text-center text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  No timeline events.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
