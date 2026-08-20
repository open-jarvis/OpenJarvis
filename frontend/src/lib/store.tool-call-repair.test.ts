import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const CONVERSATIONS_KEY = 'openjarvis-conversations';

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
}

beforeEach(() => {
  vi.resetModules();
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
});

describe('persisted tool calls', () => {
  it('repairs parsed argument objects while loading conversations', async () => {
    localStorage.setItem(
      CONVERSATIONS_KEY,
      JSON.stringify({
        version: 1,
        activeId: 'conversation-1',
        conversations: {
          'conversation-1': {
            id: 'conversation-1',
            title: 'Broken chat',
            createdAt: 1,
            updatedAt: 1,
            model: 'test-model',
            messages: [
              {
                id: 'assistant-1',
                role: 'assistant',
                content: '',
                timestamp: 1,
                toolCalls: [
                  {
                    id: 'call-1',
                    tool: 'web_search',
                    arguments: { query: 'python' },
                    status: 'success',
                  },
                ],
              },
            ],
          },
        },
      }),
    );

    const { useAppStore } = await import('./store');

    expect(useAppStore.getState().messages[0].toolCalls?.[0].arguments).toBe(
      '{"query":"python"}',
    );
    const repaired = JSON.parse(localStorage.getItem(CONVERSATIONS_KEY) ?? '{}');
    expect(
      repaired.conversations['conversation-1'].messages[0].toolCalls[0].arguments,
    ).toBe('{"query":"python"}');
  });

  it('keeps repaired conversations in memory when writeback fails', async () => {
    localStorage.setItem(
      CONVERSATIONS_KEY,
      JSON.stringify({
        version: 1,
        activeId: 'conversation-1',
        conversations: {
          'conversation-1': {
            id: 'conversation-1',
            title: 'Readable chat',
            createdAt: 1,
            updatedAt: 1,
            model: 'test-model',
            messages: [
              {
                id: 'assistant-1',
                role: 'assistant',
                content: '',
                timestamp: 1,
                toolCalls: [
                  {
                    id: 'call-1',
                    tool: 'web_search',
                    arguments: { query: 'python' },
                    status: 'success',
                  },
                ],
              },
            ],
          },
        },
      }),
    );
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage quota exceeded', 'QuotaExceededError');
    });

    const { useAppStore } = await import('./store');

    expect(useAppStore.getState().messages).toHaveLength(1);
    expect(useAppStore.getState().messages[0].toolCalls?.[0].arguments).toBe(
      '{"query":"python"}',
    );
  });
});
