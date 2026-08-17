import { useEffect, useState, useCallback } from 'react';
import { getBase } from '@/lib/api';

export type KioskState = 'idle' | 'approaching' | 'prompting' | 'active' | 'cleanup';

export interface KioskStateEvent {
  type: string;
  timestamp?: number;
  data?: { state?: unknown; mic_enabled?: unknown };
}

export interface KioskPolicy {
  state: KioskState;
  micEnabled: boolean;
}

const KIOSK_STATES: readonly KioskState[] = [
  'idle', 'approaching', 'prompting', 'active', 'cleanup',
];

function isKioskState(value: unknown): value is KioskState {
  return typeof value === 'string' && KIOSK_STATES.includes(value as KioskState);
}

export function applyKioskStateEvent(
  current: KioskPolicy,
  event: KioskStateEvent,
): KioskPolicy {
  if (event.type !== 'kiosk_state_changed' || !isKioskState(event.data?.state)) {
    return current;
  }
  return { state: event.data.state, micEnabled: event.data.mic_enabled === true };
}

function buildKioskWsUrl(): string {
  const base = getBase();
  let origin: string;
  if (base) {
    origin = base.replace(/^http/, 'ws');
  } else if (window.location.port === '5173') {
    // Vite dev server on :5173 → connect directly to backend WS on :8000
    // (cross-origin WebSocket is allowed by browsers, no CORS for WS)
    origin = 'ws://localhost:8000';
  } else {
    // Production: same origin
    const loc = window.location;
    origin = `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}`;
  }
  return `${origin}/v1/agents/events`; // no agent_id filter → receives all events
}

export function useKioskState(): {
  state: KioskState;
  micEnabled: boolean;
  respond: (accept: boolean) => Promise<void>;
} {
  const [policy, setPolicy] = useState<KioskPolicy>({ state: 'idle', micEnabled: false });

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (closed) return;
      try { ws = new WebSocket(buildKioskWsUrl()); }
      catch { schedule(); return; }
      ws.onopen = () => { retry = 0; };
      ws.onmessage = (msg) => {
        try {
          const evt = JSON.parse(msg.data) as KioskStateEvent;
          setPolicy((current) => applyKioskStateEvent(current, evt));
        } catch { /* ignore */ }
      };
      ws.onclose = () => {
        if (!closed) {
          setPolicy((current) => current.micEnabled ? { ...current, micEnabled: false } : current);
          schedule();
        }
      };
      ws.onerror = () => ws?.close();
    };
    const schedule = () => {
      if (closed) return;
      timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(retry, 5)));
      retry += 1;
    };
    connect();
    return () => { closed = true; if (timer) clearTimeout(timer); ws?.close(); };
  }, []);

  const respond = useCallback(async (accept: boolean) => {
    try {
      const base = getBase() || (
        window.location.port === '5173' ? 'http://localhost:8000' : window.location.origin
      );
      await fetch(`${base}/api/kiosk/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accept }),
      });
    } catch (e) {
      console.error('Kiosk respond failed:', e);
    }
  }, []);

  return { state: policy.state, micEnabled: policy.micEnabled, respond };
}
