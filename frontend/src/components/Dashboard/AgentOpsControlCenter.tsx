import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
} from 'lucide-react';
import {
  fetchManagedAgents,
  pauseManagedAgent,
  recoverManagedAgent,
  resumeManagedAgent,
  runManagedAgent,
} from '../../lib/api';
import type { ManagedAgent } from '../../lib/api';

const STATUS_TONE: Record<string, { color: string; bg: string; label: string }> = {
  idle: { color: 'var(--color-text-secondary)', bg: 'var(--color-bg-tertiary)', label: 'Idle' },
  running: { color: 'var(--color-accent)', bg: 'var(--color-accent-subtle)', label: 'Running' },
  paused: { color: 'var(--color-warning)', bg: 'rgba(245, 158, 11, 0.12)', label: 'Paused' },
  error: { color: 'var(--color-error)', bg: 'rgba(239, 68, 68, 0.12)', label: 'Error' },
  stalled: { color: 'var(--color-warning)', bg: 'rgba(245, 158, 11, 0.12)', label: 'Stalled' },
  needs_attention: { color: 'var(--color-warning)', bg: 'rgba(245, 158, 11, 0.12)', label: 'Attention' },
  budget_exceeded: { color: 'var(--color-error)', bg: 'rgba(239, 68, 68, 0.12)', label: 'Budget' },
};

function formatSchedule(agent: ManagedAgent): string {
  const type = agent.schedule_type || (agent.config?.schedule_type as string | undefined);
  const value = agent.schedule_value || (agent.config?.schedule_value as string | undefined);
  if (!type || type === 'manual') return 'Manual';
  if (type === 'interval' && value) {
    const seconds = Number(value);
    if (Number.isFinite(seconds) && seconds > 0) {
      if (seconds >= 3600) return `Every ${Math.round(seconds / 3600)}h`;
      if (seconds >= 60) return `Every ${Math.round(seconds / 60)}m`;
      return `Every ${seconds}s`;
    }
  }
  if (type === 'cron' && value) return `Cron ${value}`;
  return type;
}

function formatAge(ts?: number | null): string {
  if (!ts) return 'Never';
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function isStaleRunning(agent: ManagedAgent): boolean {
  if (agent.status !== 'running') return false;
  const timeout = Number(agent.config?.timeout_seconds || 1200);
  const lastSignal = agent.last_activity_at || agent.last_run_at || agent.updated_at;
  if (!lastSignal) return false;
  return Date.now() / 1000 - lastSignal > timeout;
}

function StatusBadge({ agent }: { agent: ManagedAgent }) {
  const stale = isStaleRunning(agent);
  const tone = stale
    ? { color: 'var(--color-warning)', bg: 'rgba(245, 158, 11, 0.12)', label: 'Stale' }
    : STATUS_TONE[agent.status] || STATUS_TONE.idle;
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-medium" style={{ color: tone.color, background: tone.bg }}>
      {stale && <AlertTriangle size={12} />}
      {tone.label}
    </span>
  );
}

function ActionButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      disabled={disabled}
      className="inline-flex h-8 w-8 items-center justify-center rounded-lg transition-opacity disabled:opacity-40"
      style={{ background: 'var(--color-surface)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
    >
      {children}
    </button>
  );
}

export function AgentOpsControlCenter() {
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setAgents(await fetchManagedAgents());
      setError(null);
    } catch (err: any) {
      setError(err?.message || 'Failed to load managed agents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const summary = useMemo(() => {
    return {
      total: agents.length,
      running: agents.filter((agent) => agent.status === 'running').length,
      attention: agents.filter((agent) => ['error', 'stalled', 'needs_attention', 'budget_exceeded'].includes(agent.status)).length,
      stale: agents.filter(isStaleRunning).length,
    };
  }, [agents]);

  const runAction = async (agent: ManagedAgent, action: 'run' | 'pause' | 'resume' | 'recover') => {
    setBusyId(agent.id);
    try {
      if (action === 'run') await runManagedAgent(agent.id);
      if (action === 'pause') await pauseManagedAgent(agent.id);
      if (action === 'resume') await resumeManagedAgent(agent.id);
      if (action === 'recover') await recoverManagedAgent(agent.id);
      await refresh();
    } catch (err: any) {
      setError(err?.message || `Failed to ${action} ${agent.name}`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="rounded-2xl p-4" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-sm)' }}>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold" style={{ color: 'var(--color-text)' }}>
            <Bot size={18} style={{ color: 'var(--color-accent)' }} />
            Agent Ops Control Center
          </h2>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Managed agent status, schedules, model routing, and operator actions.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium disabled:opacity-60"
          style={{ background: 'var(--color-accent)', color: 'white' }}
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      <div className="mt-4 grid grid-cols-4 gap-2">
        <Metric label="Agents" value={summary.total} tone="neutral" />
        <Metric label="Running" value={summary.running} tone="ok" />
        <Metric label="Attention" value={summary.attention} tone={summary.attention ? 'warn' : 'ok'} />
        <Metric label="Stale" value={summary.stale} tone={summary.stale ? 'warn' : 'ok'} />
      </div>

      {error && (
        <div className="mt-3 rounded-lg px-3 py-2 text-xs" style={{ background: 'rgba(239, 68, 68, 0.12)', color: 'var(--color-error)' }}>
          {error}
        </div>
      )}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[860px] border-separate border-spacing-y-2 text-left text-xs">
          <thead style={{ color: 'var(--color-text-tertiary)' }}>
            <tr>
              <th className="px-3 py-1 font-medium">Agent</th>
              <th className="px-3 py-1 font-medium">Status</th>
              <th className="px-3 py-1 font-medium">Schedule</th>
              <th className="px-3 py-1 font-medium">Model</th>
              <th className="px-3 py-1 font-medium">Runs</th>
              <th className="px-3 py-1 font-medium">Last Run</th>
              <th className="px-3 py-1 font-medium">Tools</th>
              <th className="px-3 py-1 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agent) => {
              const tools = agent.config?.tools;
              const toolCount = Array.isArray(tools) ? tools.length : typeof tools === 'string' ? tools.split(',').length : 0;
              const model = (agent.config?.model as string | undefined) || 'default';
              const canRun = agent.status !== 'running' && agent.status !== 'archived';
              const canPause = agent.status === 'running' || agent.status === 'idle';
              const canResume = agent.status === 'paused';
              const canRecover = ['error', 'stalled', 'needs_attention'].includes(agent.status) || isStaleRunning(agent);
              return (
                <tr key={agent.id} style={{ background: 'var(--color-bg-secondary)' }}>
                  <td className="rounded-l-xl px-3 py-3">
                    <div className="font-medium" style={{ color: 'var(--color-text)' }}>{agent.name}</div>
                    <div className="mt-1 font-mono text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>{agent.agent_type}</div>
                  </td>
                  <td className="px-3 py-3"><StatusBadge agent={agent} /></td>
                  <td className="px-3 py-3" style={{ color: 'var(--color-text-secondary)' }}>{formatSchedule(agent)}</td>
                  <td className="max-w-[180px] truncate px-3 py-3 font-mono" style={{ color: 'var(--color-text-secondary)' }}>{model}</td>
                  <td className="px-3 py-3" style={{ color: 'var(--color-text)' }}>{agent.total_runs ?? 0}</td>
                  <td className="px-3 py-3" style={{ color: 'var(--color-text-secondary)' }}>{formatAge(agent.last_run_at)}</td>
                  <td className="px-3 py-3" style={{ color: 'var(--color-text-secondary)' }}>{toolCount}</td>
                  <td className="rounded-r-xl px-3 py-3">
                    <div className="flex justify-end gap-1.5">
                      <ActionButton label={`Run ${agent.name}`} disabled={!canRun || busyId === agent.id} onClick={() => runAction(agent, 'run')}>
                        <Play size={13} />
                      </ActionButton>
                      <ActionButton label={`Pause ${agent.name}`} disabled={!canPause || busyId === agent.id} onClick={() => runAction(agent, 'pause')}>
                        <Pause size={13} />
                      </ActionButton>
                      {canResume && (
                        <ActionButton label={`Resume ${agent.name}`} disabled={busyId === agent.id} onClick={() => runAction(agent, 'resume')}>
                          <Activity size={13} />
                        </ActionButton>
                      )}
                      <ActionButton label={`Recover ${agent.name}`} disabled={!canRecover || busyId === agent.id} onClick={() => runAction(agent, 'recover')}>
                        <RotateCcw size={13} />
                      </ActionButton>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone: 'ok' | 'warn' | 'neutral' }) {
  const color = tone === 'ok' ? 'var(--color-success)' : tone === 'warn' ? 'var(--color-warning)' : 'var(--color-text)';
  return (
    <div className="rounded-xl p-3 text-center" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="text-lg font-semibold" style={{ color }}>{value}</div>
      <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
    </div>
  );
}
