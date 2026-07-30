import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';
import type { CanonicalTaskEvent, PendingApproval } from '../lib/api';
import { dedupeEvents, useJarvisStore } from '../lib/jarvisStore';
import { MAX_RECONNECTS } from '../lib/useCanonicalTaskStream';
import { ApprovalCard, EventCard, JarvisPage } from './JarvisPage';

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

describe('Jarvis canonical workspace', () => {
  beforeEach(() => {
    useJarvisStore.setState({
      sessionId: 'session-test',
      activeTaskId: 'task-test',
      tasks: [],
      timeline: [event(1), event(2)],
      approvals: [approval],
      sources: [],
      actions: [],
      artifacts: [],
      error: null,
      sending: false,
    });
  });

  it('deduplicates replay and live events in stable sequence order', () => {
    expect(dedupeEvents([event(2), event(1), event(2)])).toEqual([event(1), event(2)]);
    expect(MAX_RECONNECTS).toBe(6);
  });

  it('exposes keyboard and screen-reader controls without remembered approval', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/approvals']}>
        <JarvisPage />
      </MemoryRouter>,
    );

    expect(html).toContain('aria-label="Jarvis workspace sections"');
    expect(html).toContain('Cancel task');
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
});
