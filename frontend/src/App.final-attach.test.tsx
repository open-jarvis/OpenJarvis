import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  clear(): void {
    this.store.clear();
  }
}

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

describe('final desktop attach experience', () => {
  it('mounts only the focused Jarvis experience', async () => {
    (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
      new MemoryStorage();
    const { FinalAttachApp } = await import('./App');
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <FinalAttachApp />
      </MemoryRouter>,
    );

    expect(html).toContain('Jarvis Talk-Modus');
    expect(html).toContain('jarvis-core');
    expect(html).toContain('Jarvis-Menü öffnen');
    expect(html).not.toContain('CANONICAL WORKSPACE');
    expect(html).not.toContain('Task timeline');
    expect(html).not.toContain('Setting up your local AI');
    expect(html).not.toContain('API key');
    expect(html).not.toContain('Get Started');
  }, 10_000);
});
