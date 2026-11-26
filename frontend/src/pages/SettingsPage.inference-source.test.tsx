import { describe, expect, it, vi } from 'vitest';

vi.mock('../lib/store', () => ({ useAppStore: vi.fn() }));

import { inferenceSourceToSave, savedModelSelections } from './SettingsPage';

const fields = {
  customHost: 'https://api.example.com/v1',
  customEngine: 'vllm',
  customKey: '',
};

describe('Settings inference source models', () => {
  it('does not copy a saved custom model into Bundled Ollama', () => {
    const loaded = savedModelSelections({
      kind: 'custom',
      host: fields.customHost,
      model: 'meta-llama/Llama-3.1-70B-Instruct',
    });

    expect(loaded.ollamaModel).toBe('');
    expect(inferenceSourceToSave('ollama', { ...fields, ...loaded })).toEqual({
      kind: 'ollama',
      model: undefined,
    });
  });

  it('keeps a pinned Ollama model when saving Bundled Ollama', () => {
    const loaded = savedModelSelections({ kind: 'ollama', model: 'qwen3.5:9b' });

    expect(loaded.customModel).toBe('');
    expect(inferenceSourceToSave('ollama', { ...fields, ...loaded })).toEqual({
      kind: 'ollama',
      model: 'qwen3.5:9b',
    });
  });
});
