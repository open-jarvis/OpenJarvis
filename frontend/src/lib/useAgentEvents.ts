import { useEffect, useRef } from 'react';
import { getApiKey, getBase } from './api';

export interface AgentEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

export function buildWsUrl(agentId?: string): string {
  const base = getBase();
  const url = new URL('/v1/agents/events', base || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';

  if (agentId) url.searchParams.set('agent_id', agentId);
  const apiKey = getApiKey();
  if (apiKey) url.searchParams.set('token', apiKey);

  return url.toString();
}

/**
 * Subscribe to agent events over WebSocket.
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
    if (!agentId) return;
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
