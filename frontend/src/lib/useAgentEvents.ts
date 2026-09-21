import { useEffect, useRef } from 'react';
import { getApiKey, getBase } from './api';

export interface AgentEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

const WS_AUTH_PROTOCOL = 'openjarvis.auth.v1';
const WS_KEY_PROTOCOL_PREFIX = 'openjarvis.key.b64url.';

function utf8ToBase64Url(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

export function buildWsUrl(agentId?: string): string {
  const base = getBase();
  const url = new URL('/v1/agents/events', base || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';

  if (agentId) url.searchParams.set('agent_id', agentId);

  return url.toString();
}

/**
 * WebSocket auth protocols carrying the API key, if configured. The key is
 * UTF-8/base64url encoded so every value satisfies browser subprotocol syntax.
 * This keeps the key out of the request URL and request-line access logs; the
 * encoding is transport-safe, not encryption.
 */
export function buildWsProtocols(): string[] | undefined {
  const apiKey = getApiKey();
  return apiKey
    ? [
        WS_AUTH_PROTOCOL,
        `${WS_KEY_PROTOCOL_PREFIX}${utf8ToBase64Url(apiKey)}`,
      ]
    : undefined;
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
        ws = new WebSocket(buildWsUrl(agentId), buildWsProtocols());
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
