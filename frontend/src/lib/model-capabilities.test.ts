import { describe, expect, it } from 'vitest';

import { isEmbedOnlyModel } from './model-capabilities';

describe('isEmbedOnlyModel', () => {
  it.each([
    'nomic-embed-text',
    'mxbai-embed-large',
    'text-embedding-3-small',
    'all-minilm:latest',
    'hf.co/BAAI/bge-m3:latest',
  ])('classifies %s as embedding-only', (modelId) => {
    expect(isEmbedOnlyModel(modelId)).toBe(true);
  });

  it.each(['qwen3.5:4b', 'codegemma:7b'])('keeps %s available for chat', (modelId) => {
    expect(isEmbedOnlyModel(modelId)).toBe(false);
  });
});
