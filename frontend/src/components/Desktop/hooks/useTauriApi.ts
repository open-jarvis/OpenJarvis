import { useState, useEffect, useCallback } from 'react';

/**
 * Detect whether we're running inside Tauri or in a browser.
 * In Tauri, `window.__TAURI_INTERNALS__` is set.
 */
export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/**
 * Invoke a Tauri command if in Tauri, otherwise fall back to fetch.
 */
export async function tauriInvoke<T>(
  command: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  if (isTauri()) {
    const { invoke } = await import('@tauri-apps/api/core');
    return invoke<T>(command, args);
  }
  // Browser fallback: map command to REST API
  return browserFallback<T>(command, args);
}

async function browserFallback<T>(
  command: string,
  args: Record<string, unknown>,
): Promise<T> {
  const apiUrl = (args.apiUrl as string) || 'http://localhost:8000';
  const urlMap: Record<string, string> = {
    check_health: '/health',
    fetch_energy: '/v1/telemetry/energy',
    fetch_telemetry: '/v1/telemetry/stats',
    fetch_traces: `/v1/traces?limit=${args.limit || 20}`,
    fetch_trace: `/v1/traces/${args.traceId}`,
    fetch_learning_stats: '/v1/learning/stats',
    fetch_learning_policy: '/v1/learning/policy',
    fetch_memory_stats: '/v1/memory/stats',
    fetch_agents: '/v1/agents',
  };

  const path = urlMap[command];
  if (!path) {
    throw new Error(`No browser fallback for command: ${command}`);
  }

  const resp = await fetch(`${apiUrl}${path}`);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

/**
 * Hook for polling a Tauri command at a regular interval.
 */
export function usePolling<T>(
  command: string,
  args: Record<string, unknown>,
  intervalMs: number,
): { data: T | null; error: string | null; loading: boolean; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const result = await tauriInvoke<T>(command, args);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [command, JSON.stringify(args)]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, intervalMs);
    return () => clearInterval(timer);
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}
