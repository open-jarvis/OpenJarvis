import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Regression for #266: the frontend must send the local API key as a Bearer
// token on /v1 + /api requests, or `jarvis serve` with a key configured 401s
// every data-plane call. These tests cover the pure helpers (getApiKey,
// authHeaders) that source the key and build the header.

const SETTINGS_KEY = 'openjarvis-settings';

// Minimal in-memory localStorage stub so the helpers can run under node
// (no jsdom dependency).
class MemoryStorage {
  private store = new Map<string, string>();
  getItem(k: string): string | null {
    return this.store.has(k) ? (this.store.get(k) as string) : null;
  }
  setItem(k: string, v: string): void {
    this.store.set(k, String(v));
  }
  removeItem(k: string): void {
    this.store.delete(k);
  }
  clear(): void {
    this.store.clear();
  }
}

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'test-anon-key');
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.doUnmock('@tauri-apps/api/core');
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
  delete (globalThis as unknown as { window?: unknown }).window;
});

async function freshApi() {
  // Re-import to pick up the current localStorage stub.
  return await import('./api');
}

describe('getApiKey', () => {
  it('returns empty string when no key is configured', async () => {
    const { getApiKey } = await freshApi();
    expect(getApiKey()).toBe('');
  });

  it('reads apiKey from the openjarvis-settings localStorage blob', async () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'http://x', apiKey: 'sk-local-123' }),
    );
    const { getApiKey } = await freshApi();
    expect(getApiKey()).toBe('sk-local-123');
  });

  it('returns empty string when the blob has no apiKey field', async () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiUrl: 'http://x' }));
    const { getApiKey } = await freshApi();
    expect(getApiKey()).toBe('');
  });
});

describe('authHeaders', () => {
  it('omits Authorization when no key is set (keyless default unchanged)', async () => {
    const { authHeaders } = await freshApi();
    expect(authHeaders()).toEqual({});
  });

  it('adds a Bearer Authorization header when a key is set', async () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiKey: 'sk-local-123' }));
    const { authHeaders } = await freshApi();
    expect(authHeaders()).toEqual({ Authorization: 'Bearer sk-local-123' });
  });

  it('merges extra headers alongside Authorization', async () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiKey: 'sk-local-123' }));
    const { authHeaders } = await freshApi();
    expect(authHeaders({ 'Content-Type': 'application/json' })).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer sk-local-123',
    });
  });
});

describe('final desktop API base', () => {
  it('ignores stale saved and build-time URLs in attach-only mode', async () => {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      writable: true,
      value: { __TAURI_INTERNALS__: {} },
    });
    vi.stubEnv('VITE_API_URL', 'http://stale-build.example:9999');
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'http://stale-saved.example:9998' }),
    );
    vi.doMock('@tauri-apps/api/core', () => ({
      invoke: vi.fn(async (command: string) => {
        if (command === 'get_api_base') return 'http://127.0.0.1:8000';
        if (command === 'get_setup_status') return { source: 'codex' };
        throw new Error(`Unexpected command: ${command}`);
      }),
    }));

    const { getBase, initApiBase } = await freshApi();
    await initApiBase();

    expect(getBase()).toBe('http://127.0.0.1:8000');
  });
});
