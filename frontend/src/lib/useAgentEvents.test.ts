import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { buildWsUrl } from './useAgentEvents';

const SETTINGS_KEY = 'openjarvis-settings';

class MemoryStorage {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

beforeEach(() => {
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
});

describe('buildWsUrl', () => {
  it('authenticates agent events with the configured API key', () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({
        apiUrl: 'https://jarvis.example.com:8443',
        apiKey: 'secret+/=',
      }),
    );

    const url = new URL(buildWsUrl('agent/one'));

    expect(url.origin).toBe('wss://jarvis.example.com:8443');
    expect(url.pathname).toBe('/v1/agents/events');
    expect(url.searchParams.get('agent_id')).toBe('agent/one');
    expect(url.searchParams.get('token')).toBe('secret+/=');
  });

  it('normalizes a versioned API base without duplicating /v1', () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'http://192.0.2.10:8000/v1/' }),
    );

    expect(buildWsUrl()).toBe('ws://192.0.2.10:8000/v1/agents/events');
  });

  it('omits the token for a keyless server', () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'http://localhost:8000' }),
    );

    const url = new URL(buildWsUrl('agent-one'));

    expect(url.searchParams.has('token')).toBe(false);
  });
});
