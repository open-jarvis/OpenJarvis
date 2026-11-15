/** Client for ``/v1/life`` (habits, journal, focus, mission) plus a polling hook. */
import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../../lib/api';

export interface Habit { id: string; name: string; time: string; done: boolean }
export interface JournalEntry { id: string; day: string; created_at: number; text: string }
export interface Mission { title: string; stages: string[]; stage: number; percent: number }
export interface LifeSummary {
  profile: { name: string; motto: string };
  level: number;
  level_progress: number;
  stats: { days: number; habits: number; focus_hours: number };
  streak: number;
  progress: { overall: number; discipline: number; habits: number; mindset: number; focus: number };
  week: { day: string; percent: number }[];
  today: { day: string; habits: Habit[]; habits_total: number; habits_done: number };
  mission: Mission | null;
}

/** Local calendar day as YYYY-MM-DD (not UTC: a check-in belongs to the day you see). */
export function localDay(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Monday-first week containing *d*. */
export function weekOf(d: Date): Date[] {
  const monday = new Date(d);
  monday.setHours(12, 0, 0, 0);
  monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const x = new Date(monday);
    x.setDate(monday.getDate() + i);
    return x;
  });
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const send = <T>(method: string, path: string, body?: unknown) =>
  json<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const lifeApi = {
  summary: () => json<LifeSummary>(`/v1/life/summary?today=${localDay()}`),
  addHabit: (name: string, time = '') => send<Habit>('POST', '/v1/life/habits', { name, time }),
  checkHabit: (id: string, done: boolean) => send('POST', `/v1/life/habits/${id}/check`, { day: localDay(), done }),
  removeHabit: (id: string) => send('DELETE', `/v1/life/habits/${id}`),
  journal: (start: string, end: string) =>
    json<{ entries: JournalEntry[] }>(`/v1/life/journal?start=${start}&end=${end}`),
  addJournal: (text: string, day: string) => send<JournalEntry>('POST', '/v1/life/journal', { text, day }),
  deleteJournal: (id: string) => send('DELETE', `/v1/life/journal/${id}`),
  addFocus: (minutes: number, label = '') => send('POST', '/v1/life/focus', { minutes, label, day: localDay() }),
  updateProfile: (name: string, motto: string) => send('PUT', '/v1/life/profile', { name, motto }),
  setMission: (title: string, stages: string[]) => send<Mission>('PUT', '/v1/life/mission', { title, stages }),
  advanceMission: () => send<Mission>('POST', '/v1/life/mission/advance'),
  bookmarks: () => json<{ quotes: string[] }>('/v1/life/bookmarks'),
  bookmark: (quote: string, saved: boolean) => send('POST', '/v1/life/bookmarks', { quote, saved }),
};

/** Summary, refreshed every minute and after any change (call ``refresh``). */
export function useLife() {
  const [summary, setSummary] = useState<LifeSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      setSummary(await lifeApi.summary());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 60_000);
    return () => clearInterval(t);
  }, [refresh]);
  return { summary, error, refresh };
}
