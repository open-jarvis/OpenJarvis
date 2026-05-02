import { useCallback, useEffect, useMemo, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  FileText,
  Gauge,
  GitBranch,
  HardDrive,
  RefreshCw,
  Router,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  XCircle,
} from 'lucide-react';
import { fetchOpenClawHealth } from '../../lib/api';
import type { OpenClawHealth, OpenClawHealthComponent, OpenClawComponentStatus, ProjectAgentScorecard } from '../../types';

const GROUP_ICON: Record<string, LucideIcon> = {
  'control-plane': GitBranch,
  'local-llm': Cpu,
  openclaw: Router,
  'coding-agent': Terminal,
  legacy: HardDrive,
  observability: FileText,
  safety: ShieldCheck,
  'project-agents': Bot,
};

const STATUS_META: Record<OpenClawComponentStatus, { label: string; color: string; bg: string; Icon: LucideIcon }> = {
  pass: {
    label: 'Healthy',
    color: 'var(--color-success)',
    bg: 'rgba(34, 197, 94, 0.10)',
    Icon: CheckCircle2,
  },
  warn: {
    label: 'Watch',
    color: 'var(--color-warning)',
    bg: 'rgba(245, 158, 11, 0.12)',
    Icon: AlertTriangle,
  },
  fail: {
    label: 'Blocked',
    color: 'var(--color-error)',
    bg: 'rgba(239, 68, 68, 0.12)',
    Icon: XCircle,
  },
};

function formatAge(seconds: number | null): string {
  if (seconds == null) return 'not available';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function formatTimestamp(value: string): string {
  if (!value) return 'Never';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function basename(path: string): string {
  if (!path) return '';
  return path.split('/').filter(Boolean).pop() || path;
}

function componentPriority(component: OpenClawHealthComponent): number {
  if (component.status === 'fail') return 0;
  if (component.status === 'warn') return 1;
  return 2;
}

function StatusPill({ status }: { status: OpenClawComponentStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.Icon;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-medium"
      style={{ color: meta.color, background: meta.bg }}
    >
      <Icon size={12} />
      {meta.label}
    </span>
  );
}

function ScoreRing({ score, status }: { score: number; status: OpenClawHealth['status'] }) {
  const color = status === 'critical'
    ? 'var(--color-error)'
    : status === 'degraded'
      ? 'var(--color-warning)'
      : 'var(--color-success)';
  const background = `conic-gradient(${color} ${score * 3.6}deg, var(--color-bg-tertiary) 0deg)`;

  return (
    <div
      className="relative h-28 w-28 shrink-0 rounded-full p-2"
      style={{ background }}
      aria-label={`OpenClaw health score ${score}`}
    >
      <div
        className="flex h-full w-full flex-col items-center justify-center rounded-full"
        style={{ background: 'var(--color-surface)' }}
      >
        <span className="text-3xl font-semibold" style={{ color: 'var(--color-text)' }}>
          {score}
        </span>
        <span className="text-[10px] uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>
          score
        </span>
      </div>
    </div>
  );
}

function ComponentRow({ component }: { component: OpenClawHealthComponent }) {
  const Icon = GROUP_ICON[component.group] || Bot;
  return (
    <div
      className="rounded-xl p-4"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className="mt-0.5 rounded-lg p-2"
            style={{ background: 'var(--color-surface)', color: 'var(--color-accent)' }}
          >
            <Icon size={16} />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                {component.label}
              </h4>
              {component.critical && (
                <span className="rounded-full px-2 py-0.5 text-[10px]" style={{ background: 'var(--color-accent-blue-subtle)', color: 'var(--color-accent)' }}>
                  core
                </span>
              )}
            </div>
            <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
              {component.detail}
            </p>
            {component.status !== 'pass' && component.action && (
              <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--color-text-tertiary)' }}>
                Action: {component.action}
              </p>
            )}
          </div>
        </div>
        <StatusPill status={component.status} />
      </div>
    </div>
  );
}

function AgentStatusPill({ status }: { status: string }) {
  const tone: OpenClawComponentStatus = status === 'healthy'
    ? 'pass'
    : status === 'no_data'
      ? 'warn'
      : status === 'attention'
        ? 'warn'
        : status === 'unavailable'
          ? 'fail'
          : 'warn';
  const meta = STATUS_META[tone];
  return (
    <span className="rounded-full px-2 py-1 text-[10px] font-medium" style={{ color: meta.color, background: meta.bg }}>
      {status || 'unknown'}
    </span>
  );
}

function ProjectAgentRow({ agent }: { agent: ProjectAgentScorecard }) {
  const success = Math.round((agent.success_rate_last_20_runs || 0) * 100);
  const isLegacy = agent.catalog_status === 'legacy' || agent.stage === 'deprecated';
  return (
    <div className="grid gap-2 rounded-xl p-3" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium" style={{ color: 'var(--color-text)' }}>
              {agent.display_name}
            </span>
            {isLegacy && (
              <span className="rounded-full px-2 py-0.5 text-[10px]" style={{ color: 'var(--color-warning)', background: 'rgba(245, 158, 11, 0.12)' }}>
                legacy
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
            <span>{agent.agent_id}</span>
            <span>{agent.catalog_status}</span>
            <span>{agent.stage}</span>
          </div>
        </div>
        <AgentStatusPill status={agent.scorecard_status} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <MiniMetric label="Success" value={success} tone={success >= 80 ? 'ok' : 'warn'} suffix="%" />
        <MiniMetric label="24h Runs" value={agent.runs_last_24h} tone={agent.runs_last_24h ? 'ok' : 'neutral'} />
        <MiniMetric label="Median" value={agent.median_duration_ms_last_20_runs} tone="neutral" suffix="ms" />
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
        <div>
          <span style={{ color: 'var(--color-text-tertiary)' }}>Last run</span>
          <div>{formatTimestamp(agent.last_run_started_at)}</div>
        </div>
        <div>
          <span style={{ color: 'var(--color-text-tertiary)' }}>Last status</span>
          <div>{agent.last_run_status || 'unknown'}</div>
        </div>
      </div>
      {agent.latest_artifact_path && (
        <div className="truncate text-[11px]" title={agent.latest_artifact_path} style={{ color: 'var(--color-text-tertiary)' }}>
          Artifact: {basename(agent.latest_artifact_path)}
        </div>
      )}
      {agent.latest_failure_status && (
        <div className="text-[11px]" style={{ color: 'var(--color-warning)' }}>
          Latest non-success: {agent.latest_failure_status}
        </div>
      )}
    </div>
  );
}

export function OpenClawOpsDashboard() {
  const [health, setHealth] = useState<OpenClawHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await fetchOpenClawHealth();
      setHealth(next);
      setError(null);
    } catch (err: any) {
      setError(err?.message || 'Failed to load OpenClaw health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const sortedComponents = useMemo(() => {
    return [...(health?.components || [])].sort((a, b) => componentPriority(a) - componentPriority(b));
  }, [health]);

  const heroColor = health?.status === 'critical'
    ? 'var(--color-error)'
    : health?.status === 'degraded'
      ? 'var(--color-warning)'
      : 'var(--color-success)';
  const heroBg = health?.status === 'critical'
    ? 'rgba(239, 68, 68, 0.12)'
    : health?.status === 'degraded'
      ? 'rgba(245, 158, 11, 0.12)'
      : 'rgba(34, 197, 94, 0.10)';

  if (error && !health) {
    return (
      <div
        className="rounded-2xl p-6"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-error)' }}>
          <XCircle size={16} />
          {error}
        </div>
      </div>
    );
  }

  return (
    <section
      className="overflow-hidden rounded-2xl"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-sm)' }}
    >
      <div
        className="relative p-6"
        style={{
          background:
            'radial-gradient(circle at top left, rgba(59, 130, 246, 0.16), transparent 34%), linear-gradient(135deg, var(--color-surface), var(--color-bg-secondary))',
          borderBottom: '1px solid var(--color-border)',
        }}
      >
        <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
          <div className="flex items-start gap-4">
            {health ? <ScoreRing score={health.score} status={health.status} /> : (
              <div className="h-28 w-28 rounded-full animate-pulse" style={{ background: 'var(--color-bg-tertiary)' }} />
            )}
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium"
                  style={{ background: heroBg, color: heroColor }}
                >
                  <Gauge size={13} />
                  {health ? `OpenClaw ${health.status}` : 'Checking OpenClaw'}
                </span>
                {health?.latest_report.exists && (
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    Report {formatAge(health.latest_report.age_seconds)}
                  </span>
                )}
              </div>
              <h2 className="mt-3 text-2xl font-semibold tracking-tight" style={{ color: 'var(--color-text)' }}>
                Operations Health
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                OpenJarvis now tracks the control path that keeps OpenClaw useful: local Gemma4 inference, gateway reachability, Pi coding route, safety findings, and recent fatal signals.
              </p>
              {health && (
                <div className="mt-4 flex flex-wrap gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  <span>{health.primary_local_llm.model}</span>
                  <span>at {health.primary_local_llm.host}</span>
                  <span>{health.summary.passes} pass</span>
                  <span>{health.summary.warnings} warn</span>
                  <span>{health.summary.failures} fail</span>
                </div>
              )}
            </div>
          </div>

          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-60"
            style={{ background: 'var(--color-accent)', color: 'white' }}
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {health && (
        <div className="grid gap-4 p-4 lg:grid-cols-[1.6fr_1fr]">
          <div className="grid gap-3">
            {sortedComponents.map((component) => (
              <ComponentRow key={component.id} component={component} />
            ))}
          </div>

          <div className="grid content-start gap-4">
            {health.project_agents?.atop_dev && (
              <div
                className="rounded-xl p-4"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <h3 className="flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                  <Activity size={16} style={{ color: health.project_agents.atop_dev.status === 'healthy' ? 'var(--color-success)' : 'var(--color-warning)' }} />
                  ATOP_Dev Agent Performance
                </h3>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <MiniMetric label="Agents" value={health.project_agents.atop_dev.summary.agents} tone="neutral" />
                  <MiniMetric label="Healthy" value={health.project_agents.atop_dev.summary.healthy} tone="ok" />
                  <MiniMetric label="Attention" value={health.project_agents.atop_dev.summary.attention} tone={health.project_agents.atop_dev.summary.attention ? 'warn' : 'ok'} />
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  <MiniMetric label="24h Runs" value={health.project_agents.atop_dev.summary.runs_last_24h} tone={health.project_agents.atop_dev.summary.runs_last_24h ? 'ok' : 'neutral'} />
                  <MiniMetric label="Avg Success" value={Math.round((health.project_agents.atop_dev.summary.avg_success_rate || 0) * 100)} tone={health.project_agents.atop_dev.summary.avg_success_rate >= 0.95 ? 'ok' : 'warn'} suffix="%" />
                  <MiniMetric label="No Data" value={health.project_agents.atop_dev.summary.no_data} tone={health.project_agents.atop_dev.summary.no_data ? 'warn' : 'ok'} />
                </div>
                <div className="mt-3 space-y-2">
                  {health.project_agents.atop_dev.agents.map((agent) => (
                    <ProjectAgentRow key={agent.agent_id} agent={agent} />
                  ))}
                </div>
                {health.project_agents.atop_dev.error && (
                  <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--color-error)' }}>
                    {health.project_agents.atop_dev.error}
                  </p>
                )}
              </div>
            )}

            <div
              className="rounded-xl p-4"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                <ShieldAlert size={16} style={{ color: health.latest_report.security.critical ? 'var(--color-warning)' : 'var(--color-success)' }} />
                Safety Notes
              </h3>
              <div className="mt-3 grid grid-cols-3 gap-2">
                <MiniMetric label="Critical" value={health.latest_report.security.critical} tone={health.latest_report.security.critical ? 'warn' : 'ok'} />
                <MiniMetric label="Warn" value={health.latest_report.security.warn} tone={health.latest_report.security.warn ? 'warn' : 'ok'} />
                <MiniMetric label="Info" value={health.latest_report.security.info} tone="neutral" />
              </div>
              {health.latest_report.highlights.length > 0 && (
                <div className="mt-3 space-y-2">
                  {health.latest_report.highlights.map((item, index) => (
                    <p key={`${item}-${index}`} className="text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                      {item}
                    </p>
                  ))}
                </div>
              )}
            </div>

            <div
              className="rounded-xl p-4"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                Recommended Operating Rules
              </h3>
              <div className="mt-3 space-y-3">
                {health.recommendations.map((recommendation) => (
                  <div key={recommendation} className="flex gap-2 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                    <CheckCircle2 size={14} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
                    <span>{recommendation}</span>
                  </div>
                ))}
              </div>
            </div>

            <div
              className="rounded-xl p-4 text-xs leading-relaxed"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
            >
              Full report: {health.latest_report.path}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function MiniMetric({ label, value, tone, suffix = '' }: { label: string; value: number; tone: 'ok' | 'warn' | 'neutral'; suffix?: string }) {
  const color = tone === 'ok' ? 'var(--color-success)' : tone === 'warn' ? 'var(--color-warning)' : 'var(--color-text)';
  return (
    <div className="rounded-lg p-3 text-center" style={{ background: 'var(--color-surface)' }}>
      <div className="text-lg font-semibold" style={{ color }}>
        {value}{suffix}
      </div>
      <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
        {label}
      </div>
    </div>
  );
}
