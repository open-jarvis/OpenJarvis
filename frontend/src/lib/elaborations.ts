// Long-lived SSE subscriber for proactive elaborations.
// Mounted once on app boot. Reconnects with backoff on disconnect.

import { useAppStore } from './store';
import { getBase } from './api';

export interface ElaborationProposed {
  id: string;
  conversation_id: string | null;
  status: string;
  original_question_excerpt: string;
  created_at: number;
  updated_at: number;
}

export interface ElaborationAccepted extends ElaborationProposed {
  claude_answer: string;
}

let es: EventSource | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let backoffMs = 1000;

function connect(): void {
  if (es) return;
  const url = `${getBase()}/v1/elaborations/stream`;
  try {
    es = new EventSource(url);
  } catch (exc) {
    console.warn('[elaborations] failed to open SSE:', exc);
    scheduleReconnect();
    return;
  }

  es.addEventListener('ready', () => {
    backoffMs = 1000; // reset backoff on a successful hello
  });

  es.addEventListener('proposed', (ev: MessageEvent) => {
    try {
      const data: ElaborationProposed = JSON.parse(ev.data);
      useAppStore.getState().addProposedElaboration(data);
    } catch (exc) {
      console.warn('[elaborations] bad proposed payload:', exc);
    }
  });

  es.addEventListener('accepted_full', (ev: MessageEvent) => {
    try {
      const data: ElaborationAccepted = JSON.parse(ev.data);
      useAppStore.getState().resolveElaboration(data);
    } catch (exc) {
      console.warn('[elaborations] bad accepted_full payload:', exc);
    }
  });

  es.addEventListener('dismissed', (ev: MessageEvent) => {
    try {
      const { id } = JSON.parse(ev.data);
      useAppStore.getState().removeElaboration(id);
    } catch {}
  });

  // heartbeat events fire every 15s — no action needed, the connection
  // staying alive is the point.
  es.addEventListener('heartbeat', () => {});

  es.onerror = () => {
    if (es) {
      es.close();
      es = null;
    }
    scheduleReconnect();
  };
}

function scheduleReconnect(): void {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    backoffMs = Math.min(backoffMs * 2, 30_000);
    connect();
  }, backoffMs);
}

export function startElaborationStream(): void {
  if (es || reconnectTimer) return;
  connect();
}

export function stopElaborationStream(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (es) {
    es.close();
    es = null;
  }
}

export async function acceptElaboration(id: string): Promise<void> {
  await fetch(`${getBase()}/v1/elaborations/${id}/accept`, { method: 'POST' });
}

export async function dismissElaboration(id: string): Promise<void> {
  await fetch(`${getBase()}/v1/elaborations/${id}/dismiss`, { method: 'POST' });
}
