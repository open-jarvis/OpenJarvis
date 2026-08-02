import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  CanonicalTask,
  CanonicalTaskEvent,
  PendingApproval,
  ToolActionInfo,
} from '../lib/api';
import { JarvisApiError } from '../lib/api';
import { dedupeEvents, ensureActiveTaskId, isTerminalTaskStatus, useJarvisStore } from '../lib/jarvisStore';
import { MAX_RECONNECTS } from '../lib/useCanonicalTaskStream';
import {
  ApprovalCard,
  attemptCanonicalChat,
  canReplacePausedTaskForChat,
  EventCard,
  JarvisPage,
  requiresFreshTask,
  TASK_REFRESH_INTERVAL_MS,
  TurnEvidenceDetails,
} from './JarvisPage';

function event(sequence: number, eventId = `event-${sequence}`): CanonicalTaskEvent {
  return {
    event_id: eventId,
    task_id: 'task-test',
    sequence,
    event_type: 'chat.assistant_message',
    occurred_at: '2026-07-30T00:00:00Z',
    cause: 'synthetic_test',
    component: 'test',
    status_from: null,
    status_to: null,
    thread_id: null,
    item_id: null,
    approval_id: null,
    artifact_id: null,
    payload: { content: sequence === 2 ? 'مرحبا من جارفس' : 'Hallo von Jarvis' },
  };
}

const approval: PendingApproval = {
  id: 'approval-test',
  source: 'codex_task',
  task_id: 'task-test',
  action_type: 'command',
  action: 'synthetic.read',
  description: 'Read one synthetic file',
  effect: 'Read-only inspection',
  target: 'C:\\synthetic\\file.txt',
  risk_level: 1,
  sandbox: 'read_only',
  cwd: 'C:\\synthetic',
  undo: 'No mutation',
  payload: { path: 'redacted/file.txt' },
  permission_key: '',
  tier: 'low',
  status: 'pending',
  created_at: '2026-07-30T00:00:00Z',
  expires_at: '2026-07-30T00:05:00Z',
};

function task(status: string, taskId = 'task-terminal'): CanonicalTask {
  return {
    task_id: taskId,
    session_id: 'session-test',
    correlation_id: 'correlation-test',
    description: 'Synthetic task',
    status: status as CanonicalTask['status'],
    outcome: null,
    execution_lane: 'model_lane',
    backend: 'codex',
    risk_level: 0,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    result: '',
    error_category: null,
    active_thread_id: null,
    budget_warning: false,
  };
}

describe('Jarvis canonical workspace', () => {
  it('retries only an explicit higher-risk task-boundary conflict', () => {
    expect(requiresFreshTask(new JarvisApiError(
      'NEW_TASK_REQUIRED: assistant action needs a higher risk boundary',
      'conflict',
      409,
    ))).toBe(true);
    expect(requiresFreshTask(new JarvisApiError(
      'terminal task cannot accept another chat turn',
      'conflict',
      409,
    ))).toBe(false);
    expect(requiresFreshTask(new Error('NEW_TASK_REQUIRED: forged'))).toBe(false);
  });

  beforeEach(() => {
    useJarvisStore.setState({
      sessionId: 'session-test',
      activeTaskId: 'task-test',
      tasks: [],
      tasksLoaded: true,
      timeline: [event(1), event(2)],
      approvals: [approval],
      sources: [],
      actions: [],
      artifacts: [],
      error: null,
      sending: false,
      taskSummary: null,
      codexHealth: null,
    });
  });

  it('deduplicates replay and live events in stable sequence order', () => {
    expect(dedupeEvents([event(2), event(1), event(2)])).toEqual([event(1), event(2)]);
    expect(MAX_RECONNECTS).toBe(6);
    expect(TASK_REFRESH_INTERVAL_MS).toBe(15_000);
  });

  it('renders incomplete runtime DTO fields without crashing the workspace', () => {
    const incompleteEvent = {
      ...event(3),
      event_type: undefined,
      cause: undefined,
      payload: undefined,
    } as unknown as CanonicalTaskEvent;
    const incompleteTask = {
      ...task('running', 'task-test'),
      status: undefined,
    } as unknown as CanonicalTask;
    const incompleteAction = {
      action_id: 'action-incomplete',
      status: undefined,
    } as unknown as ToolActionInfo;

    expect(renderToStaticMarkup(<EventCard event={incompleteEvent} />)).toContain('Event');
    useJarvisStore.setState({
      tasks: [incompleteTask],
      timeline: [incompleteEvent],
      actions: [incompleteAction],
    });
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/']}>
        <JarvisPage />
      </MemoryRouter>,
    );

    expect(html).toContain('unknown');
    expect(html).toContain('event');
  });

  it.each(['done', 'completed', 'canceled', 'failed', 'rejected'])(
    'replaces terminal status %s before the next chat turn without changing the old timeline',
    (status) => {
      const oldTimeline = [event(1), event(2)];
      useJarvisStore.setState({
        activeTaskId: 'task-terminal',
        tasks: [task(status)],
        timeline: oldTimeline,
        lastSequence: 2,
      });

      const nextTaskId = ensureActiveTaskId();

      expect(isTerminalTaskStatus(status)).toBe(true);
      expect(nextTaskId).not.toBe('task-terminal');
      expect(nextTaskId).toMatch(/^task-/);
      expect(oldTimeline).toEqual([event(1), event(2)]);
      expect(useJarvisStore.getState().timeline).toEqual([]);
      expect(useJarvisStore.getState().lastSequence).toBe(0);
    },
  );

  it('sends the preserved message exactly once to the replacement task', async () => {
    const oldTimeline = [event(1), event(2)];
    useJarvisStore.setState({
      activeTaskId: 'task-terminal',
      tasks: [task('canceled')],
      timeline: oldTimeline,
    });
    const nextTaskId = ensureActiveTaskId();
    const failure = new Error('synthetic failure');
    const sender = vi.fn().mockRejectedValue(failure);

    const attempt = await attemptCanonicalChat(
      {
        message: 'Dieser Text bleibt erhalten.',
        session_id: 'session-test',
        task_id: nextTaskId,
        input_mode: 'text',
        use_memory: true,
      },
      { correlationId: 'correlation-test', idempotencyKey: 'idempotency-test' },
      new AbortController().signal,
      sender,
    );

    expect(sender).toHaveBeenCalledTimes(1);
    expect(sender).toHaveBeenCalledWith(
      expect.objectContaining({ task_id: nextTaskId }),
      expect.any(Object),
      expect.any(AbortSignal),
    );
    expect(attempt).toEqual({ ok: false, error: failure, draft: 'Dieser Text bleibt erhalten.' });
    expect(oldTimeline).toEqual([event(1), event(2)]);
    expect(useJarvisStore.getState().timeline).toEqual([]);
  });

  it('keeps an active running task for a normal follow-up turn', () => {
    useJarvisStore.setState({
      activeTaskId: 'task-running',
      tasks: [task('running', 'task-running')],
      timeline: [event(1)],
      lastSequence: 1,
    });

    expect(ensureActiveTaskId()).toBe('task-running');
    expect(useJarvisStore.getState().timeline).toEqual([event(1)]);
    expect(useJarvisStore.getState().lastSequence).toBe(1);
  });

  it('lets a harmless question replace a paused task without resuming it', () => {
    const paused = task('paused', 'task-paused');

    expect(canReplacePausedTaskForChat(paused, [])).toBe(true);
    expect(canReplacePausedTaskForChat({ ...paused, risk_level: 1 }, [])).toBe(false);
    expect(canReplacePausedTaskForChat(paused, [{ ...approval, task_id: 'task-paused' }])).toBe(false);
  });

  it('fails closed until a persisted task has been refreshed after restart', () => {
    useJarvisStore.setState({
      activeTaskId: 'task-from-local-storage',
      tasks: [],
      tasksLoaded: false,
    });

    expect(() => ensureActiveTaskId()).toThrow('Task status is still loading');
    expect(useJarvisStore.getState().activeTaskId).toBe('task-from-local-storage');
  });

  it('shows app-server-confirmed model and reasoning evidence for the selected turn', () => {
    const html = renderToStaticMarkup(
      <dl>
        <TurnEvidenceDetails
          evidence={{
            requested: { model: null, effort: null },
            resolved: { model: 'gpt-5.6-sol', effort: 'xhigh' },
            confirmed: { model: true, effort: true },
            evidence_source: {
              model: 'python_sdk_app_server_thread_start',
              effort: 'python_sdk_app_server_thread_start',
            },
            backend: 'python_sdk',
            sdk_version: '0.144.4',
            runtime_version: '0.144.4',
            thread_id: '…12345678',
            turn_id: null,
          }}
          fallbackBackend="codex"
          fallbackRuntimeVersion={null}
          fallbackThreadId={null}
        />
      </dl>,
    );

    expect(html).toContain('gpt-5.6-sol');
    expect(html).toContain('xhigh');
    expect(html).toContain('App Server confirmed');
    expect(html).toContain('Codex config (no model override)');
    expect(html).toContain('0.144.4');
    expect(html).toContain('…12345678');
  });

  it('offers a new task without mutating the previous timeline', () => {
    const oldTimeline = [event(1), event(2)];
    useJarvisStore.setState({ activeTaskId: 'task-terminal', timeline: oldTimeline });

    useJarvisStore.getState().startNewTask();

    expect(useJarvisStore.getState().activeTaskId).toBeNull();
    expect(oldTimeline).toEqual([event(1), event(2)]);
    expect(useJarvisStore.getState().timeline).toEqual([]);
  });

  it('exposes keyboard and screen-reader controls without remembered approval', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/approvals']}>
        <JarvisPage />
      </MemoryRouter>,
    );

    expect(html).toContain('aria-label="Jarvis workspace sections"');
    expect(html).toContain('Cancel task');
    const chatHtml = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/chat']}>
        <JarvisPage />
      </MemoryRouter>,
    );
    expect(chatHtml).toContain('Neue Aufgabe');
    const approvalHtml = renderToStaticMarkup(
      <ApprovalCard approval={approval} busy={false} onDecision={() => {}} />,
    );
    expect(approvalHtml).toContain('Allow once');
    expect(approvalHtml).toContain('Deny');
    expect(approvalHtml).not.toContain('Always allow');
    expect(approvalHtml).not.toContain('Approve all');
  });

  it('renders Arabic responses with RTL direction', () => {
    const html = renderToStaticMarkup(<EventCard event={event(2)} />);
    expect(html).toContain('dir="rtl"');
    expect(html).toContain('مرحبا من جارفس');
  });
  it('integrates Learning and Skills into the existing Jarvis navigation', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/learning']}>
        <JarvisPage />
      </MemoryRouter>,
    );
    expect(html).toContain('href="/learning"');
    expect(html).toContain('href="/skills"');
    expect(html).toContain('Select or create a canonical task');
  });
});
