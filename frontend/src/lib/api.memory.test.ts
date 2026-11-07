import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.fn<typeof fetch>();

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
}

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv('VITE_API_URL', '');
  fetchMock.mockReset();
  globalThis.fetch = fetchMock;
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage = new MemoryStorage();
});

afterEach(() => {
  vi.unstubAllEnvs();
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

describe('getMemoryStats', () => {
  it('shows the server detail and HTTP status for a backend failure', async () => {
    fetchMock.mockResolvedValue(new Response(
      JSON.stringify({ detail: 'friday_ai_rust is missing from the serving environment' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    ));
    const { getMemoryStats } = await import('./api');

    await expect(getMemoryStats()).rejects.toThrow(
      'friday_ai_rust is missing from the serving environment (HTTP 503)',
    );
  });

  it('keeps the HTTP status when a failed response has no JSON detail', async () => {
    fetchMock.mockResolvedValue(new Response('Internal Server Error', { status: 500 }));
    const { getMemoryStats } = await import('./api');

    await expect(getMemoryStats()).rejects.toThrow('Memory status request failed (HTTP 500)');
  });

  it('retries successfully against the updated API URL after a connection failure', async () => {
    localStorage.setItem('friday_ai-settings', JSON.stringify({ apiUrl: 'http://localhost:8000' }));
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ backend: 'sqlite', entries: 3 }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    const { getMemoryStats } = await import('./api');

    await expect(getMemoryStats()).rejects.toThrow(/Check the server status and API URL/);
    localStorage.setItem('friday_ai-settings', JSON.stringify({ apiUrl: 'http://localhost:8010' }));
    await expect(getMemoryStats()).resolves.toEqual({ backend: 'sqlite', entries: 3 });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://localhost:8000/v1/memory/stats',
      'http://localhost:8010/v1/memory/stats',
    ]);
  });
});
