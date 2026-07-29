import { useEffect, useRef } from 'react';
import { getBase } from './api';

export interface AgentEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

/**
 * Subscribe to every agent's events rather than one agent's.
 *
 * The server has always supported this — ``/v1/agents/events`` treats
 * ``agent_id`` as an optional filter and broadcasts everything without it
 * (`server/ws_bridge.py`). Only this hook prevented it, by refusing to connect
 * without an id, which left `buildWsUrl`'s no-filter branch unreachable.
 *
 * An explicit sentinel rather than reusing `undefined`: callers pass a
 * possibly-undefined selected-agent id and rely on that meaning "do not
 * subscribe", so redefining it would silently turn those into firehose
 * subscriptions.
 */
export const ALL_AGENTS = '*';

/** Whether the hook should open a socket at all. */
export function shouldSubscribe(agentId?: string): boolean {
  return Boolean(agentId);
}

export function buildWsUrl(agentId?: string): string {
  const base = getBase();
  let origin: string;
  if (base) {
    origin = base.replace(/^http/, 'ws');
  } else {
    const loc = window.location;
    origin = `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}`;
  }
  const path = '/v1/agents/events';
  // ALL_AGENTS means "no filter", which is the absence of the parameter —
  // sending agent_id=* would filter for an agent literally named "*".
  return agentId && agentId !== ALL_AGENTS
    ? `${origin}${path}?agent_id=${encodeURIComponent(agentId)}`
    : `${origin}${path}`;
}

/**
 * Subscribe to agent events over WebSocket.
 *
 * Pass a single agent id, or {@link ALL_AGENTS} for every agent.
 * Auto-reconnects with backoff when the socket drops.
 */
export function useAgentEvents(
  agentId: string | undefined,
  onEvent: (event: AgentEvent) => void,
  eventTypes?: readonly string[],
): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const typesRef = useRef(eventTypes);
  typesRef.current = eventTypes;

  useEffect(() => {
    if (!shouldSubscribe(agentId)) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(buildWsUrl(agentId));
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        retry = 0;
      };
      ws.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data) as AgentEvent;
          const allowed = typesRef.current;
          if (allowed && !allowed.includes(payload.type)) return;
          onEventRef.current(payload);
        } catch {
          // ignore malformed payload
        }
      };
      ws.onclose = () => {
        if (!closed) schedule();
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    const schedule = () => {
      if (closed) return;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(retry, 5));
      retry += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [agentId]);
}
