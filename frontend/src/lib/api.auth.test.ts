import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Regression for #266: the frontend must send the local API key as a Bearer
// token on /v1 + /api requests, or `jarvis serve` with a key configured 401s
// every data-plane call. These tests cover the pure helpers (getApiKey,
// authHeaders) that source the key and build the header.

const SETTINGS_KEY = 'openjarvis-settings';
const fetchMock = vi.fn<typeof fetch>();

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
  fetchMock.mockReset();
  globalThis.fetch = fetchMock;
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  vi.unstubAllEnvs();
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
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

describe('apiFetch', () => {
  it('sends request with Bearer authorization and prefixes base url for relative paths', async () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'https://jarvis.example', apiKey: 'sk-local-123' }),
    );
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { apiFetch } = await freshApi();

    await apiFetch('/api/digest');

    expect(fetchMock).toHaveBeenCalledWith('https://jarvis.example/api/digest', {
      headers: { Authorization: 'Bearer sk-local-123' },
    });
  });

  it('preserves same-server absolute URLs and does not duplicate base url', async () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'https://jarvis.example', apiKey: 'sk-local-123' }),
    );
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { apiFetch } = await freshApi();

    await apiFetch('https://jarvis.example/api/digest/audio');

    expect(fetchMock).toHaveBeenCalledWith('https://jarvis.example/api/digest/audio', {
      headers: { Authorization: 'Bearer sk-local-123' },
    });
  });

  it.each([
    'https://attacker.example/api/digest/audio',
    'http://jarvis.example/api/digest/audio',
    'https://jarvis.example:8443/api/digest/audio',
    '//attacker.example/api/digest/audio',
    'https://jarvis.example@attacker.example/audio',
    'https://attacker@jarvis.example/audio',
    'data:audio/mp3;base64,AAAA',
    'blob:https://jarvis.example/123',
    'javascript:alert(1)',
    'file:///etc/passwd',
    'https:\\attacker.example/audio',
    '/\\attacker.example/audio',
    'https://jarvis.example\n.attacker.example/audio',
  ])('rejects an unsafe destination without sending credentials: %s', async (url) => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      apiUrl: 'https://jarvis.example', apiKey: 'private-server-key',
    }));
    const { apiFetch } = await freshApi();
    await expect(apiFetch(url)).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps requests inside a configured reverse-proxy prefix', async () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      apiUrl: 'https://jarvis.example/oj', apiKey: 'private-server-key',
    }));
    fetchMock.mockResolvedValue(new Response('{}'));
    const { apiFetch } = await freshApi();
    await apiFetch('/api/digest/audio');
    expect(fetchMock.mock.calls[0][0]).toBe('https://jarvis.example/oj/api/digest/audio');
    await expect(apiFetch('https://jarvis.example/another-app/audio')).rejects.toThrow();
    await expect(apiFetch('/../another-app/audio')).rejects.toThrow();
    await expect(apiFetch('/%2e%2e%2fanother-app/audio')).rejects.toThrow();
    await expect(apiFetch('/%2e%2e%5canother-app/audio')).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('preserves relative requests on the current page origin', async () => {
    vi.stubEnv('VITE_API_URL', '');
    vi.stubGlobal('window', { location: { href: 'https://web.example/chat' } });
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiKey: 'page-api-key' }));
    fetchMock.mockResolvedValue(new Response('{}'));
    try {
      const { apiFetch } = await freshApi();
      await apiFetch('/api/digest/audio');
      expect(fetchMock).toHaveBeenCalledWith('/api/digest/audio', {
        headers: { Authorization: 'Bearer page-api-key' },
      });
      await expect(apiFetch('https://other.example/audio')).rejects.toThrow();
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('merges caller-specified headers with authHeaders', async () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'https://jarvis.example', apiKey: 'sk-local-123' }),
    );
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { apiFetch } = await freshApi();

    await apiFetch('/api/digest', { headers: { 'Custom-Header': '1' } });

    expect(fetchMock).toHaveBeenCalledWith('https://jarvis.example/api/digest', {
      headers: {
        'Custom-Header': '1',
        Authorization: 'Bearer sk-local-123',
      },
    });
  });
});

describe('managed agent channels', () => {
  beforeEach(() => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'https://jarvis.example', apiKey: 'test-key' }),
    );
  });

  it('authenticates channel binding against the configured server', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { bindAgentChannel } = await freshApi();

    await bindAgentChannel('agent-1', 'sendblue', { phone: '+15555550123' });

    expect(fetchMock).toHaveBeenCalledWith(
      'https://jarvis.example/v1/managed-agents/agent-1/channels',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer test-key',
        },
        body: JSON.stringify({
          channel_type: 'sendblue',
          config: { phone: '+15555550123' },
          routing_mode: 'dedicated',
        }),
      },
    );
  });

  it('authenticates channel removal', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const { unbindAgentChannel } = await freshApi();

    await unbindAgentChannel('agent-1', 'binding-1');

    expect(fetchMock).toHaveBeenCalledWith(
      'https://jarvis.example/v1/managed-agents/agent-1/channels/binding-1',
      { method: 'DELETE', headers: { Authorization: 'Bearer test-key' } },
    );
  });
});

describe('tool credentials', () => {
  it('reads credential status from the local server', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ TAVILY_API_KEY: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const { fetchToolCredentialStatus } = await freshApi();

    await expect(fetchToolCredentialStatus('web_search')).resolves.toEqual({
      TAVILY_API_KEY: true,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/v1/tools/web_search/credentials/status',
      { headers: {} },
    );
  });

  it('saves a tool credential through the local server', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { saveToolCredentials } = await freshApi();

    await saveToolCredentials('web_search', {
      TAVILY_API_KEY: 'tvly-test',
    });

    expect(fetchMock).toHaveBeenCalledWith('/v1/tools/web_search/credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ TAVILY_API_KEY: 'tvly-test' }),
    });
  });

  it('deletes a tool credential through the local server', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { deleteToolCredential } = await freshApi();

    await deleteToolCredential('web_search', 'TAVILY_API_KEY');

    expect(fetchMock).toHaveBeenCalledWith(
      '/v1/tools/web_search/credentials/TAVILY_API_KEY',
      { method: 'DELETE', headers: {} },
    );
  });
});
