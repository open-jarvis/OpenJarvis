import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ModelInfo } from '../types';

class MemoryStorage {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const model = (id: string): ModelInfo => ({
  id,
  object: 'model',
  created: 0,
  owned_by: 'openjarvis',
});

beforeEach(() => {
  vi.resetModules();
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
});

describe('setModels', () => {
  it('retains the selected Luna model after reloading the store', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setSelectedModel('gpt-5.6-luna');
    vi.resetModules();
    const { useAppStore: reloaded } = await import('./store');
    expect(reloaded.getState().selectedModel).toBe('gpt-5.6-luna');
    // /v1/models can list only the installed engine's models; Cloud Models
    // is a separate picker and Luna need not be in that response.
    reloaded.getState().setModels([model('other-model')]);
    expect(reloaded.getState().selectedModel).toBe('gpt-5.6-luna');
  });

  it('does not replace the bound model during an active Voice session', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setSelectedModel('gpt-5.6-luna');
    useAppStore.getState().setVoiceSessionActive(true);
    useAppStore.getState().setModels([model('other-model')]);
    useAppStore.getState().setSelectedModel('other-model');
    expect(useAppStore.getState().selectedModel).toBe('gpt-5.6-luna');
    useAppStore.getState().setVoiceSessionActive(false);
    useAppStore.getState().setSelectedModel('other-model');
    expect(useAppStore.getState().selectedModel).toBe('other-model');
  });

  it('does not select an embedding-only model', async () => {
    const { useAppStore } = await import('./store');

    useAppStore.getState().setModels([model('nomic-embed-text')]);

    expect(useAppStore.getState().selectedModel).toBe('');
  });

  it('clears a missing selection when no chat fallback exists', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setSelectedModel('deleted-chat-model');

    useAppStore.getState().setModels([model('nomic-embed-text')]);

    expect(useAppStore.getState().selectedModel).toBe('');
  });

  it('replaces an embedding selection with an available chat model', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setSelectedModel('all-minilm:latest');

    useAppStore.getState().setModels([
      model('all-minilm:latest'),
      model('qwen3.5:4b'),
    ]);

    expect(useAppStore.getState().selectedModel).toBe('qwen3.5:4b');
  });
});
