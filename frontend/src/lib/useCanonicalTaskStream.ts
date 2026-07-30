import { useEffect, useRef } from 'react';
import type { CanonicalTaskEvent } from './api';
import { getApiKey, getBase } from './api';
import { useJarvisStore } from './jarvisStore';

const MAX_RECONNECTS = 6;

function taskSocketUrl(taskId: string, afterSequence: number): string {
  const base = getBase() || window.location.origin;
  const url = new URL('/v1/tasks/events', base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('task_id', taskId);
  url.searchParams.set('after_sequence', String(afterSequence));
  const token = getApiKey();
  if (token) url.searchParams.set('token', token);
  return url.toString();
}

export function useCanonicalTaskStream(taskId: string | null): void {
  const mergeTimeline = useJarvisStore((state) => state.mergeTimeline);
  const setStream = useJarvisStore((state) => state.setStream);
  const lastSequenceRef = useRef(0);

  useEffect(() => {
    if (!taskId) {
      setStream('idle');
      return;
    }
    let active = true;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let attempts = 0;
    lastSequenceRef.current = useJarvisStore.getState().lastSequence;

    const connect = () => {
      if (!active) return;
      setStream(attempts === 0 ? 'connecting' : 'reconnecting', attempts);
      socket = new WebSocket(taskSocketUrl(taskId, lastSequenceRef.current));
      socket.onopen = () => {
        attempts = 0;
        setStream('live', 0);
      };
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data) as {
            type?: string;
            data?: CanonicalTaskEvent;
          };
          const event = payload.data;
          if (!event || typeof event.event_id !== 'string' || typeof event.sequence !== 'number') return;
          if (event.task_id !== taskId || event.sequence <= lastSequenceRef.current) return;
          lastSequenceRef.current = event.sequence;
          mergeTimeline([event]);
        } catch {
          // Ignore malformed frames. The persisted replay remains authoritative.
        }
      };
      socket.onclose = (event) => {
        if (!active || event.code === 1000) return;
        attempts += 1;
        if (attempts > MAX_RECONNECTS) {
          setStream('offline', MAX_RECONNECTS);
          return;
        }
        setStream('reconnecting', attempts);
        const delay = Math.min(1000 * 2 ** (attempts - 1), 15_000);
        reconnectTimer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      active = false;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close(1000, 'component unmounted');
      setStream('idle');
    };
  }, [taskId, mergeTimeline, setStream]);
}

export { MAX_RECONNECTS, taskSocketUrl };
