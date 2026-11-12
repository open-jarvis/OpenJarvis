import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch } from '../../lib/api';

export interface AutomationRunSummary {
  success: boolean;
  finished_at: string | null;
  result: string;
  error: string;
}

export interface Automation {
  id: string;
  name: string;
  prompt: string;
  schedule_type: 'cron' | 'interval' | 'once';
  schedule_value: string;
  timezone: string;
  status: string;
  next_run: string | null;
  last_run: string | null;
  last_result: AutomationRunSummary | null;
}

export interface AutomationRun extends AutomationRunSummary {
  id: number;
  task_id: string;
  name: string;
}

export interface AutomationStatus {
  scheduler_running: boolean;
  timezone: string | null;
  local_model: string;
  claude: { model: string; key_set: boolean; available: boolean };
  claude_code: { ready: boolean; reason: string };
  agent_tools: string[];
}

export interface PendingApproval {
  id: string;
  action_type: string;
  description: string;
  payload: Record<string, unknown>;
  created_at: string;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const post = (path: string, body?: unknown) =>
  json<unknown>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const automationApi = {
  status: () => json<AutomationStatus>('/v1/automations/status'),
  list: () => json<{ automations: Automation[]; latest_run_id: number }>('/v1/automations'),
  create: (body: {
    name: string;
    prompt: string;
    schedule_type: string;
    schedule_value: string;
    timezone: string;
  }) => post('/v1/automations', body) as Promise<Automation>,
  pause: (id: string) => post(`/v1/automations/${id}/pause`),
  resume: (id: string) => post(`/v1/automations/${id}/resume`),
  runNow: (id: string) => post(`/v1/automations/${id}/run`),
  remove: (id: string) => json<unknown>(`/v1/automations/${id}`, { method: 'DELETE' }),
  runs: (id: string) => json<{ runs: AutomationRun[] }>(`/v1/automations/${id}/runs?limit=8`),
  recentRuns: (afterId: number) =>
    json<{ runs: AutomationRun[]; latest_run_id: number }>(
      `/v1/automations/runs/recent?after_id=${afterId}`,
    ),
  setTimezone: (timezone: string) => post('/v1/automations/settings', { timezone }),
  pendingApprovals: () => json<{ actions: PendingApproval[] }>('/v1/approvals/pending'),
  approve: (id: string) => post(`/v1/approvals/${id}/approve`),
  deny: (id: string) => post(`/v1/approvals/${id}/deny`),
};

export const browserTimezone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    return '';
  }
};

/** Polls status + list; exposes a refresh for after mutations. */
export function useAutomations(enabled: boolean, intervalMs = 15000) {
  const [status, setStatus] = useState<AutomationStatus | null>(null);
  const [items, setItems] = useState<Automation[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([automationApi.status(), automationApi.list().catch(() => null)]);
      setStatus(s);
      if (l) setItems(l.automations);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refresh();
    const t = setInterval(refresh, intervalMs);
    return () => clearInterval(t);
  }, [enabled, intervalMs, refresh]);

  return { status, items, error, refresh };
}

/** Calls onRun for every routine run that finishes after the hook mounts. */
export function useRunFeed(onRun: (run: AutomationRun) => void, intervalMs = 10000) {
  const lastId = useRef<number | null>(null);
  const cb = useRef(onRun);
  cb.current = onRun;

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        if (lastId.current === null) {
          const r = await automationApi.recentRuns(Number.MAX_SAFE_INTEGER);
          lastId.current = r.latest_run_id;
          return;
        }
        const r = await automationApi.recentRuns(lastId.current);
        if (cancelled) return;
        for (const run of r.runs) cb.current(run);
        lastId.current = Math.max(lastId.current, r.latest_run_id);
      } catch {
        /* scheduler offline - try again next tick */
      }
    };
    void tick();
    const t = setInterval(tick, intervalMs);
    return () => { cancelled = true; clearInterval(t); };
  }, [intervalMs]);
}
