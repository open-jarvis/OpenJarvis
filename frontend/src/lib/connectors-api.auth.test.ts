import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Regression: every call in connectors-api.ts must go through apiFetch()
// (not a bare fetch()) so the Bearer auth header is attached when
// OPENJARVIS_API_KEY is set. Direct fetch() calls silently 401 against an
// authenticated server -- the same bug class #266 fixed in api.ts, which
// this file was missed by. Confirmed live: with a real server + API key
// configured, /v1/connectors 401'd from the browser while every other
// endpoint (which already went through apiFetch) worked.

const SETTINGS_KEY = 'openjarvis-settings';
const fetchMock = vi.fn<typeof fetch>();

// Minimal in-memory localStorage stub so the helpers can run under node
// (no jsdom dependency) -- mirrors api.auth.test.ts.
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
  fetchMock.mockReset();
  globalThis.fetch = fetchMock;
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
  localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify({ apiKey: 'sk-local-123' }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
});

async function freshConnectorsApi() {
  // Re-import to pick up the current localStorage stub.
  return await import('./connectors-api');
}

function okJson(body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function authHeaderSent(): string | undefined {
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit?];
  const headers = init?.headers as Record<string, string> | undefined;
  return headers?.Authorization;
}

describe('connectors-api sends the Bearer auth header', () => {
  it('listConnectors', async () => {
    fetchMock.mockResolvedValue(okJson({ connectors: [] }));
    const { listConnectors } = await freshConnectorsApi();
    await listConnectors();
    expect(authHeaderSent()).toBe('Bearer sk-local-123');
  });

  it('getConnector', async () => {
    fetchMock.mockResolvedValue(okJson({}));
    const { getConnector } = await freshConnectorsApi();
    await getConnector('gmail');
    expect(authHeaderSent()).toBe('Bearer sk-local-123');
  });

  it('connectSource', async () => {
    fetchMock.mockResolvedValue(okJson({}));
    const { connectSource } = await freshConnectorsApi();
    await connectSource('gmail', {});
    expect(authHeaderSent()).toBe('Bearer sk-local-123');
  });

  it('disconnectSource', async () => {
    fetchMock.mockResolvedValue(okJson({}));
    const { disconnectSource } = await freshConnectorsApi();
    await disconnectSource('gmail');
    expect(authHeaderSent()).toBe('Bearer sk-local-123');
  });

  it('getSyncStatus', async () => {
    fetchMock.mockResolvedValue(okJson({}));
    const { getSyncStatus } = await freshConnectorsApi();
    await getSyncStatus('gmail');
    expect(authHeaderSent()).toBe('Bearer sk-local-123');
  });

  it('triggerSync', async () => {
    fetchMock.mockResolvedValue(okJson({}));
    const { triggerSync } = await freshConnectorsApi();
    await triggerSync('gmail');
    expect(authHeaderSent()).toBe('Bearer sk-local-123');
  });
});
