import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  ChevronRight,
  Clock,
  FileCheck2,
  Globe2,
  Shield,
  Wrench,
} from 'lucide-react';
import {
  approveToolAction,
  denyToolAction,
  fetchActionArtifacts,
  fetchBrowserHealth,
  fetchBrowserSessions,
  fetchCanonicalTasks,
  fetchCodexRuntimeHealth,
  fetchRegisteredTools,
  fetchTaskActions,
  fetchTaskTimeline,
  fetchTaskUsage,
  fetchToolHealth,
} from '../lib/api';
import type {
  BrowserHealthInfo,
  BrowserSessionInfo,
  CanonicalTask,
  CanonicalTaskEvent,
  CanonicalTaskUsage,
  CodexRuntimeHealth,
  ToolActionInfo,
  ToolArtifactInfo,
  ToolHealth,
  ToolManifestInfo,
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

export function ToolActionDetails({
  action,
  tool,
  artifacts,
  decisionPending = false,
  onApprove,
  onDeny,
}: {
  action: ToolActionInfo;
  tool: ToolManifestInfo | null;
  artifacts: ToolArtifactInfo[];
  decisionPending?: boolean;
  onApprove?: () => void;
  onDeny?: () => void;
}) {
  return (
    <div
      className="mb-3 rounded-lg p-3 text-[11px]"
      style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <span className="font-mono" style={{ color: 'var(--color-text)' }}>
          {action.tool_id} · {action.status.replace('_', ' ')}
        </span>
        <span style={{ color: action.risk_level >= 3 ? 'var(--color-error)' : 'var(--color-warning)' }}>
          Risk {action.risk_level} · {action.capability}
        </span>
      </div>
      <div className="grid sm:grid-cols-2 gap-x-4 gap-y-1" style={{ color: 'var(--color-text-secondary)' }}>
        <span>Target: {action.target}</span>
        <span>Expected effect: {action.expected_side_effect}</span>
        <span>Verification: {action.verification_status}</span>
        <span>Approval: {action.approval_id || 'not required'}</span>
        <span>Root: {tool?.allowed_roots.join(', ') || 'runtime-scoped'}</span>
        <span>Undo: {action.undo_plan}</span>
      </div>
      <div className="mt-2" style={{ color: 'var(--color-text-secondary)' }}>
        Parameters: <code>{JSON.stringify(action.parameter_summary)}</code>
      </div>
      <div className="mt-1" style={{ color: 'var(--color-text-secondary)' }}>
        Expected result: {action.expected_result}
      </div>
      {action.error && (
        <div className="mt-2" style={{ color: 'var(--color-error)' }}>Error: {action.error}</div>
      )}
      {action.status === 'waiting_approval' && (
        <div className="mt-3 rounded-md p-2" style={{ border: '1px solid var(--color-warning)' }}>
          <div style={{ color: 'var(--color-warning)' }}>
            Review this exact action. Approval applies once; there is no “always allow”.
          </div>
          <div className="flex gap-2 mt-2">
            <button
              type="button"
              disabled={decisionPending}
              onClick={onApprove}
              className="px-2 py-1 rounded cursor-pointer disabled:opacity-50"
              style={{ background: 'var(--color-accent)', color: 'white' }}
            >
              Allow once
            </button>
            <button
              type="button"
              disabled={decisionPending}
              onClick={onDeny}
              className="px-2 py-1 rounded cursor-pointer disabled:opacity-50"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            >
              Deny
            </button>
          </div>
        </div>
      )}
      {artifacts.length > 0 && (
        <div className="mt-3 space-y-1">
          {artifacts.map(artifact => (
            <div key={artifact.artifact_id} className="flex items-center gap-2">
              <FileCheck2 size={11} />
              <span>{artifact.kind}</span>
              <span>{artifact.size_bytes.toLocaleString()} bytes</span>
              <span className="font-mono">sha256:{artifact.sha256.slice(0, 12)}…</span>
              {artifact.restore_of && <span>restore of {artifact.restore_of}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CodexTasksPanel() {
  const [tasks, setTasks] = useState<CanonicalTask[]>([]);
  const [health, setHealth] = useState<CodexRuntimeHealth | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [events, setEvents] = useState<CanonicalTaskEvent[]>([]);
  const [usage, setUsage] = useState<CanonicalTaskUsage | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [tools, setTools] = useState<ToolManifestInfo[]>([]);
  const [toolHealth, setToolHealth] = useState<ToolHealth | null>(null);
  const [browserHealth, setBrowserHealth] = useState<BrowserHealthInfo[]>([]);
  const [browserSessions, setBrowserSessions] = useState<BrowserSessionInfo[]>([]);
  const [actions, setActions] = useState<ToolActionInfo[]>([]);
  const [artifacts, setArtifacts] = useState<ToolArtifactInfo[]>([]);
  const [decisionPending, setDecisionPending] = useState(false);

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
      const phase5 = await Promise.allSettled([
        fetchRegisteredTools(),
        fetchToolHealth(),
        fetchBrowserHealth(),
        fetchBrowserSessions(),
      ]);
      if (phase5[0].status === 'fulfilled') setTools(phase5[0].value);
      if (phase5[1].status === 'fulfilled') setToolHealth(phase5[1].value);
      if (phase5[2].status === 'fulfilled') setBrowserHealth(phase5[2].value);
      if (phase5[3].status === 'fulfilled') setBrowserSessions(phase5[3].value);
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
      setUsage(null);
      setActions([]);
      setArtifacts([]);
      return;
    }
    let active = true;
    const load = async () => {
      try {
        const [nextEvents, nextUsage, nextActions] = await Promise.all([
          fetchTaskTimeline(selectedId),
          fetchTaskUsage(selectedId),
          fetchTaskActions(selectedId),
        ]);
        if (active) {
          setEvents(nextEvents);
          setUsage(nextUsage);
          setActions(nextActions);
          const latest = nextActions[nextActions.length - 1];
          setArtifacts(latest ? await fetchActionArtifacts(latest.action_id) : []);
        }
      } catch {
        if (active) {
          setEvents([]);
          setUsage(null);
          setActions([]);
          setArtifacts([]);
        }
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
  const latestUsage = usage?.turns[usage.turns.length - 1];
  const currentAction = actions[actions.length - 1] ?? null;
  const currentTool = currentAction
    ? tools.find(tool => tool.tool_id === currentAction.tool_id) ?? null
    : null;
  const currentBrowser = browserSessions[0] ?? null;
  const currentBrowserHealth = currentBrowser
    ? browserHealth.find(item => item.session_id === currentBrowser.session_id) ?? null
    : null;
  const currentStep = [...events]
    .reverse()
    .find(event => event.event_type.startsWith('tool.') || event.event_type.startsWith('browser.'));

  const decide = async (allow: boolean) => {
    if (!currentAction) return;
    setDecisionPending(true);
    try {
      const updated = allow
        ? await approveToolAction(currentAction.action_id)
        : await denyToolAction(currentAction.action_id);
      setActions(current => current.map(action => action.action_id === updated.action_id ? updated : action));
    } finally {
      setDecisionPending(false);
    }
  };

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
          {toolHealth && (
            <span className="flex items-center gap-1" style={{ color: toolHealth.healthy ? 'var(--color-success)' : 'var(--color-warning)' }}>
              <Wrench size={11} />
              {toolHealth.available}/{toolHealth.registered} tools
            </span>
          )}
          {currentBrowser && (
            <span className="flex items-center gap-1" style={{ color: currentBrowserHealth?.healthy ? 'var(--color-success)' : 'var(--color-warning)' }}>
              <Globe2 size={11} />
              PID {currentBrowser.browser_pid || 'stopped'} · port {currentBrowser.control_port}
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
                {currentStep && <span>Current step {currentStep.event_type}</span>}
                {usage && (
                  <>
                    <span>
                      Turn input {latestUsage?.input_tokens.toLocaleString() ?? 0}
                    </span>
                    <span>
                      Turn output {latestUsage?.output_tokens.toLocaleString() ?? 0}
                    </span>
                    <span>
                      Thread input {usage.cumulative_thread.input_tokens.toLocaleString()}
                    </span>
                    <span>
                      Thread output {usage.cumulative_thread.output_tokens.toLocaleString()}
                    </span>
                  </>
                )}
              </div>
            )}
            {currentAction && (
              <ToolActionDetails
                action={currentAction}
                tool={currentTool}
                artifacts={artifacts}
                decisionPending={decisionPending}
                onApprove={() => void decide(true)}
                onDeny={() => void decide(false)}
              />
            )}
            {currentBrowser && (
              <div className="mb-3 rounded-lg p-3 text-[11px]" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
                <div className="flex items-center gap-2 mb-1" style={{ color: 'var(--color-text)' }}>
                  <Globe2 size={12} /> Browser control
                </div>
                <div className="grid sm:grid-cols-2 gap-1">
                  <span>Browser process: {currentBrowser.browser_pid || 'not running'}</span>
                  <span>Control service: {currentBrowser.control_service_pid || 'not running'}</span>
                  <span>Port: {currentBrowser.control_port} ({currentBrowserHealth?.port_open ? 'open' : 'closed'})</span>
                  <span>Recovery: {currentBrowser.recovery_attempts}/{currentBrowser.maximum_recovery_attempts}</span>
                  <span>Checkpoint: {currentBrowser.safe_checkpoint}</span>
                  <span>Health: {currentBrowserHealth?.cause || currentBrowser.status}</span>
                </div>
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
