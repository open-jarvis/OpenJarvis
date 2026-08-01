import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Activity,
  AlertTriangle,
  Ban,
  Bot,
  CheckCircle2,
  CircleStop,
  Database,
  FileCheck2,
  Globe2,
  Loader2,
  Mic,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Send,
  ShieldAlert,
  Square,
  Volume2,
  VolumeX,
  Wrench,
} from 'lucide-react';
import {
  approveAction,
  cancelCanonicalTask,
  createMutationContext,
  denyAction,
  fetchBrowserHealth,
  fetchCanonicalTasks,
  fetchCodexRuntimeHealth,
  fetchPendingApprovals,
  fetchRegisteredTools,
  fetchSessions,
  fetchSystemHealth,
  fetchTaskActions,
  fetchTaskArtifacts,
  fetchTaskSources,
  fetchTaskSummary,
  fetchTaskTimeline,
  fetchToolHealth,
  interruptCanonicalTask,
  JarvisApiError,
  pauseCanonicalTask,
  resumeCanonicalTask,
  sendCanonicalChat,
} from '../lib/api';
import type { CanonicalTaskEvent, MutationContext, PendingApproval, TurnModelEvidence } from '../lib/api';
import { ensureActiveTaskId, isTerminalTaskStatus, useJarvisStore } from '../lib/jarvisStore';
import { useCanonicalTaskStream } from '../lib/useCanonicalTaskStream';
import { useSpeech } from '../hooks/useSpeech';
import { useTextToSpeech } from '../hooks/useTextToSpeech';
import { Phase7Panel } from '../components/Jarvis/Phase7Panel';
import { WebsiteStagingPanel } from '../components/WebsiteStagingPanel';

type WorkspaceFocus = 'chat' | 'tasks' | 'approvals' | 'tools' | 'browser' | 'website-staging' | 'learning' | 'skills' | 'overview';

type CanonicalChatSender = typeof sendCanonicalChat;

export async function attemptCanonicalChat(
  body: Parameters<CanonicalChatSender>[0],
  mutation: MutationContext,
  signal: AbortSignal,
  sender: CanonicalChatSender = sendCanonicalChat,
) {
  try {
    return { ok: true as const, response: await sender(body, mutation, signal) };
  } catch (error) {
    return { ok: false as const, error, draft: body.message };
  }
}

export function TurnEvidenceDetails({
  evidence,
  fallbackBackend,
  fallbackRuntimeVersion,
  fallbackThreadId,
}: {
  evidence: TurnModelEvidence | null;
  fallbackBackend: string;
  fallbackRuntimeVersion: string | null;
  fallbackThreadId: string | null;
}) {
  return (
    <>
      <dt>Backend</dt><dd>{evidence?.backend || fallbackBackend}</dd>
      <dt>Model</dt>
      <dd>
        {evidence?.resolved.model || 'unknown'}
        {evidence?.confirmed.model ? ' · App Server confirmed' : ' · unconfirmed'}
      </dd>
      <dt>Reasoning</dt>
      <dd>
        {evidence?.resolved.effort || 'unknown'}
        {evidence?.confirmed.effort ? ' · App Server confirmed' : ' · unconfirmed'}
      </dd>
      <dt>Requested</dt>
      <dd>
        {evidence?.requested.model || 'Codex config (no model override)'} ·{' '}
        {evidence?.requested.effort || 'Codex config (no effort override)'}
      </dd>
      <dt>SDK</dt><dd>{evidence?.sdk_version || 'unknown'}</dd>
      <dt>Pinned runtime</dt><dd>{evidence?.runtime_version || fallbackRuntimeVersion || 'unknown'}</dd>
      <dt>Thread</dt><dd>{evidence?.thread_id || fallbackThreadId || 'Not started'}</dd>
    </>
  );
}

const EVENT_LABELS: Record<string, string> = {
  'task.created': 'Task created',
  'task.state_changed': 'Task status changed',
  'task.resume_requested': 'Resume requested',
  'chat.user_message': 'You',
  'chat.assistant_message': 'Jarvis',
  'chat.response_missing': 'Response missing',
  'memory.query_started': 'Searching memory',
  'memory.candidate_found': 'Memory candidate considered',
  'memory.source_selected': 'Memory source selected',
  'memory.evidence_insufficient': 'Insufficient evidence',
  'memory.conflict_detected': 'Memory conflict',
  'memory.retrieval_failed': 'Memory retrieval unavailable',
  'tool.proposed': 'Tool proposed',
  'tool.validated': 'Tool validated',
  'tool.waiting_approval': 'Tool waiting for approval',
  'tool.started': 'Tool started',
  'tool.output': 'Tool output recorded',
  'tool.verification_started': 'Verification started',
  'tool.verified': 'Tool result verified',
  'tool.verification_failed': 'Tool verification failed',
  'tool.completed': 'Tool completed',
  'tool.failed': 'Tool failed',
  'approval.requested': 'Approval requested',
  'approval.user_decided': 'Approval decided',
  'browser.recovery_started': 'Browser recovery started',
  'browser.reconnected': 'Browser reconnected',
  'browser.recovery_failed': 'Browser recovery failed',
  'routing.recommended': 'Shadow route recommended',
  'routing.shadow_compared': 'Shadow route compared',
  'feedback.recorded': 'Feedback recorded',
  'feedback.revised': 'Feedback revised',
  'feedback.revoked': 'Feedback revoked',
  'evaluation.completed': 'Trace evaluation completed',
  'candidate.created': 'Learning candidate created',
  'candidate.revised': 'Learning candidate revised',
  'candidate.quarantined': 'Learning candidate quarantined',
  'conflict.resolved': 'Learning conflict resolved',
  'skill.test_started': 'Skill tests started',
  'skill.verified': 'Skill verified',
  'skill.promotion_requested': 'Skill promotion requested',
  'skill.promoted': 'Skill promoted',
  'skill.activated': 'Skill activated',
  'skill.execution_started': 'Skill execution started',
  'skill.execution_completed': 'Skill execution completed',
  'skill.execution_failed': 'Skill execution failed',
  'skill.deprecated': 'Skill deprecated',
  'skill.rolled_back': 'Skill rolled back',
  'website.staging.previewed': 'Website preview created',
  'website.staging.verified': 'Website artifacts verified',
  'website.staging.rolled_back': 'Website staging rolled back',
};

function focusForPath(path: string): WorkspaceFocus {
  if (path.startsWith('/tasks')) return 'tasks';
  if (path.startsWith('/approvals')) return 'approvals';
  if (path.startsWith('/tools')) return 'tools';
  if (path.startsWith('/browser')) return 'browser';
  if (path.startsWith('/website-staging')) return 'website-staging';
  if (path.startsWith('/learning')) return 'learning';
  if (path.startsWith('/skills')) return 'skills';
  if (path.startsWith('/chat')) return 'chat';
  return 'overview';
}

function readableEvent(event: CanonicalTaskEvent): string {
  if (EVENT_LABELS[event.event_type]) return EVENT_LABELS[event.event_type];
  if (event.event_type.includes('plan')) return 'Plan updated';
  if (event.event_type.includes('error') || event.event_type.includes('failed')) return 'Error';
  return event.event_type.replace(/[._]/g, ' ');
}

function eventTone(event: CanonicalTaskEvent): 'normal' | 'warning' | 'error' | 'success' {
  if (event.event_type.includes('failed') || event.event_type.includes('error')) return 'error';
  if (event.event_type.includes('insufficient') || event.event_type.includes('approval')) return 'warning';
  if (event.event_type.includes('verified') || event.status_to === 'done') return 'success';
  return 'normal';
}

function messageDirection(text: string): 'rtl' | 'ltr' | 'auto' {
  return /[\u0600-\u06ff]/.test(text) ? 'rtl' : 'auto';
}

export function EventCard({ event }: { event: CanonicalTaskEvent }) {
  const content = typeof event.payload.content === 'string' ? event.payload.content : '';
  const role = event.event_type === 'chat.user_message'
    ? 'user'
    : event.event_type === 'chat.assistant_message'
      ? 'assistant'
      : null;
  const tone = eventTone(event);
  const color = tone === 'error'
    ? 'var(--color-error)'
    : tone === 'warning'
      ? 'var(--color-warning)'
      : tone === 'success'
        ? 'var(--color-success)'
        : 'var(--color-text-secondary)';

  if (role && content) {
    return (
      <article
        className={`max-w-[88%] rounded-2xl px-4 py-3 ${role === 'user' ? 'ml-auto' : 'mr-auto'}`}
        style={{
          background: role === 'user' ? 'var(--color-user-bubble)' : 'var(--color-surface)',
          color: role === 'user' ? 'var(--color-user-bubble-text)' : 'var(--color-text)',
          border: role === 'assistant' ? '1px solid var(--color-border)' : undefined,
        }}
        aria-label={role === 'user' ? 'Your message' : 'Jarvis response'}
        dir={messageDirection(content)}
      >
        <div className="text-[11px] font-semibold mb-1 opacity-70">
          {role === 'user' ? 'You' : 'Jarvis'}
        </div>
        {role === 'assistant' ? (
          <div className="prose"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div>
        ) : (
          <p className="whitespace-pre-wrap text-sm">{content}</p>
        )}
        {event.payload.truncated === true && (
          <p className="mt-2 text-xs" style={{ color }}>
            Large content is stored as an artifact; this is a redacted preview.
          </p>
        )}
      </article>
    );
  }

  return (
    <article
      className="rounded-xl px-3 py-2 text-xs"
      style={{ background: 'var(--color-bg-secondary)', borderLeft: `3px solid ${color}` }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong style={{ color: 'var(--color-text)' }}>{readableEvent(event)}</strong>
        <span className="hud-mono" style={{ color: 'var(--color-text-tertiary)' }}>
          #{event.sequence} · {new Date(event.occurred_at).toLocaleTimeString()}
        </span>
      </div>
      <p className="mt-1" style={{ color }}>
        {event.status_from && event.status_to
          ? `${event.status_from.replace(/_/g, ' ')} → ${event.status_to.replace(/_/g, ' ')}`
          : event.cause.replace(/_/g, ' ')}
      </p>
    </article>
  );
}

export function ApprovalCard({
  approval,
  busy,
  onDecision,
}: {
  approval: PendingApproval;
  busy: boolean;
  onDecision: (allow: boolean) => void;
}) {
  return (
    <article
      className="rounded-xl p-4"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-warning)' }}
      aria-labelledby={`approval-${approval.id}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`approval-${approval.id}`} className="font-semibold text-sm">
          {approval.action || approval.action_type}
        </h3>
        <span className="text-xs" style={{ color: 'var(--color-warning)' }}>
          Risk {approval.risk_level ?? approval.tier} · expires {new Date(approval.expires_at).toLocaleTimeString()}
        </span>
      </div>
      <dl className="grid sm:grid-cols-[9rem_1fr] gap-x-3 gap-y-1 mt-3 text-xs">
        <dt>Tool/action</dt><dd>{approval.action || approval.action_type}</dd>
        <dt>Target</dt><dd className="break-all">{approval.target || 'Not specified'}</dd>
        <dt>Expected effect</dt><dd>{approval.effect || approval.description}</dd>
        <dt>Sandbox/root</dt><dd>{approval.sandbox || approval.cwd || 'Runtime scoped'}</dd>
        <dt>Undo</dt><dd>{approval.undo || 'No automatic undo available'}</dd>
        <dt>Task</dt><dd className="font-mono break-all">{approval.task_id || 'Legacy proactive action'}</dd>
      </dl>
      <p className="mt-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        Parameters: {JSON.stringify(approval.payload || {})}
      </p>
      <div className="mt-4 flex flex-col sm:flex-row gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => onDecision(true)}
          className="rounded-lg px-4 py-2 font-semibold disabled:opacity-50 focus-visible:outline-2"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          Allow once
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onDecision(false)}
          className="rounded-lg px-4 py-2 font-semibold disabled:opacity-50 focus-visible:outline-2"
          style={{ border: '2px solid var(--color-error)', color: 'var(--color-error)' }}
        >
          Deny
        </button>
      </div>
    </article>
  );
}

export function JarvisPage() {
  const location = useLocation();
  const focus = focusForPath(location.pathname);
  const state = useJarvisStore();
  const [draft, setDraft] = useState('');
  const [inputMode, setInputMode] = useState<'text' | 'voice'>('text');
  const [decisionBusy, setDecisionBusy] = useState<string | null>(null);
  const sendGuard = useRef(false);
  const sendController = useRef<AbortController | null>(null);
  const listEndRef = useRef<HTMLDivElement>(null);
  const speech = useSpeech();
  const tts = useTextToSpeech();

  useCanonicalTaskStream(state.activeTaskId);

  const activeTask = state.tasks.find((task) => task.task_id === state.activeTaskId) ?? null;
  const summaryMatchesActive = !!activeTask
    && state.taskSummary?.task.task_id === activeTask.task_id;
  const healthMatchesActive = !!activeTask
    && state.codexHealth?.active_task?.task_id === activeTask.task_id;
  const turnEvidence = summaryMatchesActive
    ? state.taskSummary?.turn_model_evidence ?? null
    : healthMatchesActive
      ? state.codexHealth?.turn_model_evidence ?? null
      : null;
  const chatTurnBlocked = !!activeTask
    && !isTerminalTaskStatus(activeTask.status)
    && !['pending', 'running'].includes(activeTask.status);
  const persistedTaskPending = !!state.activeTaskId && !state.tasksLoaded;
  const activeApprovals = state.approvals.filter(
    (item) => !item.task_id || item.task_id === state.activeTaskId,
  );
  const latestAnswer = [...state.timeline].reverse().find(
    (event) => event.event_type === 'chat.assistant_message',
  );
  const latestAnswerDigest = typeof latestAnswer?.payload.sha256 === 'string'
    ? latestAnswer.payload.sha256
    : null;

  const refreshGlobal = useCallback(async (signal?: AbortSignal) => {
    state.setLoading(true);
    const results = await Promise.allSettled([
      fetchCanonicalTasks(),
      fetchSessions(signal),
      fetchCodexRuntimeHealth(),
      fetchPendingApprovals(),
      fetchRegisteredTools(),
      fetchToolHealth(),
      fetchBrowserHealth(),
      fetchSystemHealth(signal),
    ]);
    if (results[0].status === 'fulfilled') state.setTasks(results[0].value);
    if (results[1].status === 'fulfilled') state.setSessions(results[1].value);
    if (results[2].status === 'fulfilled') state.setHealth({ codexHealth: results[2].value });
    if (results[3].status === 'fulfilled') state.setApprovals(results[3].value);
    if (results[4].status === 'fulfilled') state.setTools(results[4].value);
    if (results[5].status === 'fulfilled') state.setHealth({ toolHealth: results[5].value });
    if (results[6].status === 'fulfilled') state.setHealth({ browserHealth: results[6].value });
    if (results[7].status === 'fulfilled') state.setHealth({ systemHealth: results[7].value });
    if (results.every((item) => item.status === 'rejected')) {
      state.setError('OpenJarvis server is not reachable. Check the local server and retry.');
    }
    state.setLoading(false);
  }, []); // Store actions are stable Zustand references.

  const refreshTask = useCallback(async (taskId: string, signal?: AbortSignal) => {
    const results = await Promise.allSettled([
      fetchTaskTimeline(taskId, 0, signal),
      fetchTaskSources(taskId, signal),
      fetchTaskActions(taskId),
      fetchTaskSummary(taskId, signal),
      fetchTaskArtifacts(taskId, signal),
    ]);
    if (results[0].status === 'fulfilled') state.setTimeline(results[0].value);
    if (results[1].status === 'fulfilled') state.setSources(results[1].value);
    if (results[2].status === 'fulfilled') state.setActions(results[2].value);
    if (results[3].status === 'fulfilled') {
      state.setHealth({ taskSummary: results[3].value });
      state.upsertTask(results[3].value.task);
    }
    if (results[4].status === 'fulfilled') state.setArtifacts(results[4].value);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshGlobal(controller.signal);
    const timer = window.setInterval(() => void refreshGlobal(controller.signal), 15_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refreshGlobal]);

  useEffect(() => {
    if (!state.activeTaskId) return;
    const controller = new AbortController();
    void refreshTask(state.activeTaskId, controller.signal);
    return () => controller.abort();
  }, [state.activeTaskId, refreshTask]);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ block: 'nearest' });
  }, [state.timeline.length]);

  const submit = async () => {
    const submittedDraft = draft;
    const message = submittedDraft.trim();
    if (!message || state.sending || sendGuard.current) return;
    if (persistedTaskPending) {
      state.setError('The previous task status is still loading. Wait briefly or choose Neue Aufgabe.');
      return;
    }
    if (chatTurnBlocked) {
      state.setError('This task must be resumed or resolved before it can accept another chat turn.');
      return;
    }
    sendGuard.current = true;
    state.setSending(true);
    state.setError(null);
    const taskId = ensureActiveTaskId();
    const mutation = createMutationContext('jarvis-chat');
    const controller = new AbortController();
    sendController.current = controller;
    setDraft('');
    const failedDraft = submittedDraft;
    try {
      const attempt = await attemptCanonicalChat(
        {
          message,
          session_id: state.sessionId,
          task_id: taskId,
          input_mode: inputMode,
          use_memory: true,
        },
        mutation,
        controller.signal,
      );
      if (!attempt.ok) {
        throw attempt.error;
      }
      const response = attempt.response;
      state.upsertTask(response.task);
      await refreshTask(taskId);
      await refreshGlobal();
      setInputMode('text');
    } catch (error) {
      if (error instanceof JarvisApiError && error.category === 'aborted') {
        state.setError('The UI request was canceled. Use “Interrupt turn” to stop Codex itself.');
      } else {
        state.setError(error instanceof Error ? error.message : 'Jarvis could not process the message.');
      }
      setDraft(failedDraft);
    } finally {
      sendController.current = null;
      state.setSending(false);
      sendGuard.current = false;
    }
  };

  const controlTask = async (action: 'pause' | 'resume' | 'interrupt' | 'cancel') => {
    if (!state.activeTaskId) return;
    state.setError(null);
    const mutation = createMutationContext(`task-${action}`);
    try {
      const task = action === 'pause'
        ? await pauseCanonicalTask(state.activeTaskId, mutation)
        : action === 'resume'
          ? await resumeCanonicalTask(state.activeTaskId, mutation)
          : action === 'interrupt'
            ? await interruptCanonicalTask(state.activeTaskId, mutation)
            : await cancelCanonicalTask(state.activeTaskId, mutation);
      state.upsertTask(task);
      await refreshTask(task.task_id);
    } catch (error) {
      state.setError(error instanceof Error ? error.message : `Could not ${action} task.`);
    }
  };

  const decide = async (approval: PendingApproval, allow: boolean) => {
    if (decisionBusy) return;
    setDecisionBusy(approval.id);
    try {
      if (allow) await approveAction(approval.id);
      else await denyAction(approval.id);
      await refreshGlobal();
      if (state.activeTaskId) await refreshTask(state.activeTaskId);
    } catch (error) {
      state.setError(error instanceof Error ? error.message : 'Approval decision failed.');
    } finally {
      setDecisionBusy(null);
    }
  };

  const toggleRecording = async () => {
    tts.stop();
    if (speech.isRecording) {
      try {
        const transcript = await speech.stopRecording();
        setDraft((current) => `${current}${current ? ' ' : ''}${transcript}`);
        setInputMode('voice');
      } catch {
        // useSpeech exposes the user-safe error below.
      }
    } else {
      await speech.startRecording();
    }
  };

  const speakLatest = () => {
    const latest = [...state.timeline].reverse().find(
      (event) => event.event_type === 'chat.assistant_message'
        && typeof event.payload.content === 'string',
    );
    const content = latest?.payload.content;
    if (typeof content === 'string') tts.speak(content);
  };

  const stopSpeaking = tts.stop;

  const statusText = activeTask
    ? activeTask.status.replace(/_/g, ' ')
    : 'ready for a new task';
  const streamText = state.streamStatus === 'live'
    ? 'Timeline live'
    : state.streamStatus === 'reconnecting'
      ? `Reconnecting (${state.streamAttempts}/6)`
      : state.streamStatus === 'offline'
        ? 'Live updates unavailable; persisted replay remains available'
        : 'Timeline idle';

  const focusTabs = [
    ['/', 'Jarvis'],
    ['/chat', 'Chat'],
    ['/tasks', 'Tasks'],
    ['/approvals', 'Approvals'],
    ['/tools', 'Tools & actions'],
    ['/browser', 'Browser'],
    ['/website-staging', 'Website staging'],
    ['/learning', 'Learning'],
    ['/skills', 'Skills'],
  ] as const;

  const shouldShowChat = focus === 'overview' || focus === 'chat';
  const shouldShowTimeline = focus === 'overview' || focus === 'tasks' || focus === 'chat';

  return (
    <div className="h-full overflow-y-auto" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto w-full max-w-[1500px] p-3 sm:p-5 lg:p-6">
        <header className="hud-panel p-4 sm:p-5 mb-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="hud-label">OPENJARVIS · CANONICAL WORKSPACE</p>
              <h1 className="text-xl sm:text-2xl font-semibold mt-1">Jarvis</h1>
              <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                One session, one task authority, one auditable timeline.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs" aria-live="polite">
              <span className="rounded-full px-3 py-1" style={{ background: 'var(--color-bg-tertiary)' }}>
                Session {state.sessionId.slice(-8)}
              </span>
              <span className="rounded-full px-3 py-1" style={{ background: 'var(--color-bg-tertiary)' }}>
                {activeTask ? `Task ${activeTask.task_id.slice(-8)}` : 'No active task'}
              </span>
              <span className="rounded-full px-3 py-1" style={{ background: 'var(--color-accent-subtle)' }}>
                {statusText}
              </span>
            </div>
          </div>
          <nav className="mt-4 flex gap-2 overflow-x-auto" aria-label="Jarvis workspace sections">
            {focusTabs.map(([path, label]) => {
              const selected = path === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(path);
              return (
                <Link
                  key={path}
                  to={path}
                  aria-current={selected ? 'page' : undefined}
                  className="whitespace-nowrap rounded-lg px-3 py-2 text-sm focus-visible:outline-2"
                  style={{
                    background: selected ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
                    color: selected ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  }}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        </header>

        <div className="jarvis-workspace-grid grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.8fr)]">
          <main className="min-w-0 space-y-4">
            {state.error && (
              <div
                role="alert"
                className="rounded-xl p-3 flex items-start gap-2"
                style={{ background: 'color-mix(in srgb, var(--color-error) 10%, transparent)', border: '1px solid var(--color-error)' }}
              >
                <AlertTriangle size={18} className="shrink-0 mt-0.5" />
                <span className="text-sm">{state.error}</span>
              </div>
            )}

            {shouldShowChat && (
              <section className="hud-panel flex flex-col min-h-[34rem]" aria-labelledby="chat-heading">
                <div className="px-4 py-3 flex flex-wrap items-center justify-between gap-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <div>
                    <h2 id="chat-heading" className="font-semibold">Chat</h2>
                    <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{streamText}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={state.sending || (!!activeTask && !isTerminalTaskStatus(activeTask.status))}
                      onClick={state.startNewTask}
                      className="rounded-lg px-3 py-2 text-xs disabled:opacity-40 focus-visible:outline-2"
                      style={{ border: '1px solid var(--color-border)' }}
                    >
                      <Plus size={14} className="inline mr-1" /> Neue Aufgabe
                    </button>
                    <button type="button" onClick={state.speech.speaking ? stopSpeaking : speakLatest} className="rounded-lg px-3 py-2 text-xs focus-visible:outline-2" style={{ border: '1px solid var(--color-border)' }}>
                      {state.speech.speaking ? <VolumeX size={14} className="inline mr-1" /> : <Volume2 size={14} className="inline mr-1" />}
                      {state.speech.speaking ? 'Stop speech' : 'Read answer'}
                    </button>
                    <button type="button" disabled={!activeTask || activeTask.status !== 'running'} onClick={() => void controlTask('interrupt')} className="rounded-lg px-3 py-2 text-xs disabled:opacity-40 focus-visible:outline-2" style={{ border: '1px solid var(--color-border)' }}>
                      <CircleStop size={14} className="inline mr-1" /> Interrupt turn
                    </button>
                  </div>
                </div>
                <div className="flex-1 p-4 space-y-3 overflow-y-auto max-h-[54vh]" aria-live="polite" aria-busy={state.sending}>
                  {state.timeline.length === 0 && (
                    <div className="h-full min-h-64 grid place-items-center text-center">
                      <div>
                        <Bot size={36} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} />
                        <p className="font-medium">No task is running.</p>
                        <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                          Type or dictate a message. Voice creates the same canonical task as text.
                        </p>
                      </div>
                    </div>
                  )}
                  {state.timeline.map((event) => <EventCard key={event.event_id} event={event} />)}
                  {state.sending && (
                    <div className="flex items-center gap-2 text-sm" role="status">
                      <Loader2 size={16} className="animate-spin" /> Jarvis is working…
                    </div>
                  )}
                  <div ref={listEndRef} />
                </div>
                <div className="p-3 sm:p-4" style={{ borderTop: '1px solid var(--color-border)' }}>
                  {(speech.error || state.speech.lastError) && (
                    <p role="alert" className="mb-2 text-xs" style={{ color: 'var(--color-error)' }}>
                      {speech.error || state.speech.lastError}
                    </p>
                  )}
                  <label htmlFor="jarvis-message" className="sr-only">Message to Jarvis</label>
                  <textarea
                    id="jarvis-message"
                    value={draft}
                    onChange={(event) => { setDraft(event.target.value); if (inputMode === 'voice') setInputMode('text'); }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        void submit();
                      }
                    }}
                    dir="auto"
                    rows={3}
                    placeholder="Message Jarvis…"
                    className="w-full resize-y rounded-xl p-3 text-sm focus-visible:outline-2"
                    style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }}
                  />
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void toggleRecording()}
                        disabled={speech.isTranscribing}
                        aria-label={speech.isRecording ? 'Stop microphone recording' : 'Start push-to-talk recording'}
                        aria-pressed={speech.isRecording}
                        className="rounded-lg px-3 py-2 text-sm disabled:opacity-40 focus-visible:outline-2"
                        style={{
                          background: speech.isRecording ? 'var(--color-error)' : 'var(--color-bg-secondary)',
                          color: speech.isRecording ? 'white' : 'var(--color-text)',
                        }}
                      >
                        {speech.isRecording ? <Square size={15} className="inline mr-2" /> : <Mic size={15} className="inline mr-2" />}
                        {speech.isRecording ? 'Stop recording' : speech.isTranscribing ? 'Transcribing…' : 'Push to talk'}
                      </button>
                      <span className="text-xs" aria-live="polite" style={{ color: 'var(--color-text-secondary)' }}>
                        {speech.isRecording ? 'Microphone active' : inputMode === 'voice' ? 'Editable voice transcript' : 'Text input'}
                      </span>
                      <label className="sr-only" htmlFor="speech-language">Speech language</label>
                      <select
                        id="speech-language"
                        value={state.speech.language}
                        onChange={(event) => state.setSpeech({ language: event.target.value })}
                        className="rounded-lg px-2 py-2 text-xs focus-visible:outline-2"
                        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                      >
                        <option value="de-DE">Deutsch</option>
                        <option value="ar-SA">العربية</option>
                        <option value="en-US">English</option>
                      </select>
                    </div>
                    <button
                      type="button"
                      onClick={() => void submit()}
                      disabled={!draft.trim() || state.sending || chatTurnBlocked || persistedTaskPending}
                      className="rounded-lg px-4 py-2 font-semibold disabled:opacity-40 focus-visible:outline-2"
                      style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
                    >
                      <Send size={15} className="inline mr-2" /> Send
                    </button>
                  </div>
                </div>
              </section>
            )}

            {(focus === 'overview' || focus === 'approvals') && (
              <section className="hud-panel p-4" aria-labelledby="approvals-heading">
                <div className="flex items-center justify-between gap-3 mb-3">
                  <h2 id="approvals-heading" className="font-semibold">Approvals</h2>
                  <span className="text-xs">{activeApprovals.length} open</span>
                </div>
                <div className="space-y-3">
                  {activeApprovals.map((approval) => (
                    <ApprovalCard key={approval.id} approval={approval} busy={decisionBusy === approval.id} onDecision={(allow) => void decide(approval, allow)} />
                  ))}
                  {activeApprovals.length === 0 && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>No approval is waiting. Approvals can only be decided with the explicit buttons here.</p>}
                </div>
              </section>
            )}

            {shouldShowTimeline && focus !== 'chat' && (
              <section className="hud-panel p-4" aria-labelledby="timeline-heading">
                <h2 id="timeline-heading" className="font-semibold mb-3">Task timeline</h2>
                <div className="space-y-2">
                  {state.timeline.map((event) => <EventCard key={event.event_id} event={event} />)}
                  {state.timeline.length === 0 && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>No persisted events yet.</p>}
                </div>
              </section>
            )}

            {(focus === 'overview' || focus === 'tools') && (
              <section className="hud-panel p-4" aria-labelledby="tools-heading">
                <h2 id="tools-heading" className="font-semibold mb-3">Tools and actions</h2>
                {state.actions.length === 0 ? (
                  <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>No tool action is planned or running for this task.</p>
                ) : state.actions.map((action) => (
                  <article key={action.action_id} className="rounded-xl p-3 mb-3" style={{ background: 'var(--color-bg-secondary)' }}>
                    <div className="flex flex-wrap justify-between gap-2 text-sm">
                      <strong><Wrench size={14} className="inline mr-2" />{action.tool_id}</strong>
                      <span>Risk {action.risk_level} · {action.status.replace(/_/g, ' ')}</span>
                    </div>
                    <dl className="grid sm:grid-cols-[9rem_1fr] gap-x-3 gap-y-1 mt-2 text-xs">
                      <dt>Target</dt><dd>{action.target}</dd>
                      <dt>Expected effect</dt><dd>{action.expected_side_effect}</dd>
                      <dt>Verification plan</dt><dd>{action.verification_plan}</dd>
                      <dt>Verification</dt><dd>{action.verification_status}</dd>
                      <dt>Undo</dt><dd>{action.undo_plan}</dd>
                    </dl>
                  </article>
                ))}
                {state.artifacts.length > 0 && (
                  <div className="mt-3">
                    <h3 className="text-sm font-semibold">Artifacts</h3>
                    {state.artifacts.map((artifact) => (
                      <p key={artifact.artifact_id} className="text-xs mt-1"><FileCheck2 size={13} className="inline mr-1" />{artifact.kind} · {artifact.byte_size.toLocaleString()} bytes · sha256:{artifact.sha256.slice(0, 12)}…</p>
                    ))}
                  </div>
                )}
              </section>
            )}

            {focus === 'browser' && (
              <section className="hud-panel p-4" aria-labelledby="browser-heading">
                <h2 id="browser-heading" className="font-semibold mb-3"><Globe2 size={15} className="inline mr-2" />Owned browser sessions</h2>
                {state.browserHealth.length === 0 ? (
                  <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>No temporary OpenJarvis browser session is running.</p>
                ) : state.browserHealth.map((session) => (
                  <article key={session.session_id} className="rounded-xl p-3 mb-3 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
                    <strong>{session.healthy ? 'Healthy' : 'Degraded'} owned session</strong>
                    <dl className="grid sm:grid-cols-[10rem_1fr] gap-x-3 gap-y-1 mt-2 text-xs">
                      <dt>Control</dt><dd>{session.connection_ok ? 'connected' : 'unavailable'}</dd>
                      <dt>Port ownership</dt><dd>{session.port_owner_matches ? 'verified' : 'not verified'}</dd>
                      <dt>Recovery cause</dt><dd>{session.cause || 'none'}</dd>
                    </dl>
                  </article>
                ))}
              </section>
            )}

            {(focus === 'learning' || focus === 'skills') && (
              <Phase7Panel
                mode={focus}
                taskId={state.activeTaskId}
                sessionId={state.sessionId}
                answerId={latestAnswer?.event_id || null}
                answerDigest={latestAnswerDigest}
                onChanged={() => {
                  if (state.activeTaskId) void refreshTask(state.activeTaskId);
                }}
              />
            )}

            {focus === 'website-staging' && <WebsiteStagingPanel />}
          </main>

          <aside className="space-y-4 min-w-0" aria-label="Task context and system health">
            <section className="hud-panel p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="font-semibold">Active task</h2>
                <button type="button" onClick={() => void refreshGlobal()} aria-label="Refresh workspace" className="rounded-lg p-2 focus-visible:outline-2"><RefreshCw size={15} /></button>
              </div>
              {!activeTask ? (
                <p className="text-sm mt-3" style={{ color: 'var(--color-text-secondary)' }}>No task is active. The first message creates one.</p>
              ) : (
                <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2 mt-3 text-xs">
                  <dt>Status</dt><dd>{activeTask.status.replace(/_/g, ' ')}</dd>
                  <dt>Current step</dt><dd>{state.taskSummary?.current_step ? readableEvent({ event_type: state.taskSummary.current_step } as CanonicalTaskEvent) : 'Waiting for input'}</dd>
                  <dt>Outcome</dt><dd>{activeTask.outcome || 'Not final'}</dd>
                  <TurnEvidenceDetails
                    evidence={turnEvidence}
                    fallbackBackend={activeTask.backend}
                    fallbackRuntimeVersion={state.codexHealth?.runtime_version || null}
                    fallbackThreadId={activeTask.active_thread_id}
                  />
                  <dt>Sandbox</dt><dd>{state.codexHealth?.sandbox || 'unknown'}</dd>
                  <dt>Risk level</dt><dd>{activeTask.risk_level}</dd>
                </dl>
              )}
              <div className="mt-4 grid grid-cols-2 gap-2">
                <button type="button" disabled={!activeTask || activeTask.status !== 'running'} onClick={() => void controlTask('pause')} className="rounded-lg px-3 py-2 text-xs disabled:opacity-40 focus-visible:outline-2" style={{ border: '1px solid var(--color-border)' }}><Pause size={13} className="inline mr-1" /> Pause</button>
                <button type="button" disabled={!activeTask || !['paused', 'recovering'].includes(activeTask.status)} onClick={() => void controlTask('resume')} className="rounded-lg px-3 py-2 text-xs disabled:opacity-40 focus-visible:outline-2" style={{ border: '1px solid var(--color-border)' }}><Play size={13} className="inline mr-1" /> Resume</button>
                <button type="button" disabled={!activeTask || activeTask.status !== 'running'} onClick={() => void controlTask('interrupt')} className="rounded-lg px-3 py-2 text-xs disabled:opacity-40 focus-visible:outline-2" style={{ border: '1px solid var(--color-border)' }}><CircleStop size={13} className="inline mr-1" /> Interrupt turn</button>
                <button type="button" disabled={!activeTask || isTerminalTaskStatus(activeTask.status)} onClick={() => void controlTask('cancel')} className="rounded-lg px-3 py-2 text-xs disabled:opacity-40 focus-visible:outline-2" style={{ border: '2px solid var(--color-error)', color: 'var(--color-error)' }}><Ban size={13} className="inline mr-1" /> Cancel task</button>
              </div>
            </section>

            <section className="hud-panel p-4" aria-labelledby="sources-heading">
              <h2 id="sources-heading" className="font-semibold"><Database size={15} className="inline mr-2" />Sources</h2>
              <div className="mt-3 space-y-2">
                {state.sources.map((source) => (
                  <article key={source.source_id} className="rounded-lg p-3 text-xs" style={{ background: 'var(--color-bg-secondary)' }}>
                    <strong>{source.metadata.title || source.external_id}</strong>
                    <p className="mt-1 break-all">{source.metadata.path || source.source_kind}</p>
                    {(source.metadata.line_start || source.metadata.line_end) && <p>Lines {String(source.metadata.line_start || '?')}–{String(source.metadata.line_end || '?')}</p>}
                    {source.metadata.relevant_preview && <p className="mt-2" dir="auto">{source.metadata.relevant_preview}</p>}
                  </article>
                ))}
                {state.sources.length === 0 && <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>insufficient_evidence · no selected source</p>}
              </div>
            </section>

            <section className="hud-panel p-4" aria-labelledby="health-heading">
              <h2 id="health-heading" className="font-semibold"><Activity size={15} className="inline mr-2" />System health</h2>
              <ul className="mt-3 space-y-2 text-xs" aria-live="polite">
                <li><CheckCircle2 size={13} className="inline mr-2" />System {state.loading ? 'checking' : state.systemHealth?.status || 'unavailable'} · {state.systemHealth?.version || 'unknown version'}</li>
                <li><Bot size={13} className="inline mr-2" />Codex {state.codexHealth?.active_backend || 'unavailable'} · ChatGPT {state.codexHealth?.chatgpt_authenticated ? 'signed in' : 'not signed in'}</li>
                <li><ShieldAlert size={13} className="inline mr-2" />{state.codexHealth?.sandbox || 'unknown sandbox'} · {state.codexHealth?.approval_mode || 'unknown approval mode'}</li>
                <li><Wrench size={13} className="inline mr-2" />Tools {state.toolHealth ? `${state.toolHealth.available}/${state.toolHealth.registered}` : 'unavailable'}</li>
                <li><Globe2 size={13} className="inline mr-2" />Browser {state.browserHealth.length ? state.browserHealth.every((item) => item.healthy) ? 'healthy' : 'degraded' : 'not running'}</li>
                <li><Mic size={13} className="inline mr-2" />STT {speech.providerId} · TTS {tts.providerId}</li>
                <li><Database size={13} className="inline mr-2" />Memory {state.systemHealth?.components.memory?.status || 'unavailable'} · FTS5 {state.systemHealth?.components.memory?.fts5_available === true ? 'ready' : 'unavailable'}</li>
                <li><Activity size={13} className="inline mr-2" />Task store {state.systemHealth?.components.task_store?.status || 'unavailable'} · Trace store {state.systemHealth?.components.trace_store?.status || 'unavailable'}</li>
                <li><ShieldAlert size={13} className="inline mr-2" />{state.systemHealth?.pending_approvals ?? activeApprovals.length} approval(s) waiting</li>
                <li><Activity size={13} className="inline mr-2" />{state.systemHealth?.open_tasks ?? 0} open task(s) · last error {state.systemHealth?.last_error_category || 'none'}</li>
              </ul>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
