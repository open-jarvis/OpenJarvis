import { afterEach, describe, expect, it } from 'vitest';

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
}

afterEach(() => {
  delete (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage;
});

async function heading() {
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
  return (await import('./SetupScreen')).setupHeading;
}

describe('SetupScreen attach-only presentation', () => {
  it('uses Codex runtime copy instead of the local-AI bootstrap copy', async () => {
    const setupHeading = await heading();
    expect(setupHeading('codex')).toBe('Connecting to OpenJarvis Codex Runtime...');
    expect(setupHeading('codex')).not.toContain('local AI');
  });

  it('uses neutral copy before the first bounded status response', async () => {
    const setupHeading = await heading();
    expect(setupHeading()).toBe('Starting OpenJarvis...');
  });
});
