import { describe, expect, it } from 'vitest';

import { audioFromCompletionChunk, engineFromCompletionChunk, resolveChatEngine } from './chat-telemetry';

describe('chat engine telemetry', () => {
  it('reads the routed engine from the completion finish chunk', () => {
    expect(
      engineFromCompletionChunk({
        choices: [{ finish_reason: 'stop' }],
        telemetry: { engine: 'cloud' },
      }),
    ).toBe('cloud');
  });

  it('uses the routed cloud engine instead of a multi-engine server label', () => {
    expect(
      resolveChatEngine({
        routedEngine: 'cloud',
        serverEngine: 'multi',
        selectedModel: 'vendor-short-alias',
      }),
    ).toBe('cloud');
  });

  it('uses the routed LiteLLM engine for provider aliases', () => {
    expect(
      resolveChatEngine({
        routedEngine: 'litellm',
        serverEngine: 'multi',
        selectedModel: 'fast',
      }),
    ).toBe('litellm');
  });

  it('carries the per-request finish label through the streamed chat flow', () => {
    const chunks = [
      { choices: [{ delta: { role: 'assistant' } }] },
      { choices: [{ delta: { content: 'local answer' } }] },
      {
        choices: [{ delta: {}, finish_reason: 'stop' }],
        telemetry: { engine: 'ollama' },
      },
    ];
    let routedEngine: string | undefined;
    for (const chunk of chunks) {
      routedEngine = engineFromCompletionChunk(chunk) ?? routedEngine;
    }

    expect(
      resolveChatEngine({
        routedEngine,
        serverEngine: 'multi',
        selectedModel: 'qwen3:8b',
      }),
    ).toBe('ollama');
  });

  it('falls back to server info, then the legacy model heuristic', () => {
    expect(
      resolveChatEngine({
        serverEngine: 'nim',
        selectedModel: 'short',
      }),
    ).toBe('nim');
    expect(resolveChatEngine({ selectedModel: 'gpt-5' })).toBe('cloud');
    expect(resolveChatEngine({ selectedModel: 'qwen3:8b' })).toBe('ollama');
  });
});

describe('audioFromCompletionChunk', () => {
  // Regression: the desktop UI used to ask /api/digest after every reply and
  // attach the digest player whenever one existed. That is a question about
  // the server, not about this answer, so once the morning digest had written
  // a .wav every ordinary chat reply grew an audio player for it.
  it('reads audio from the completion that produced it', () => {
    expect(
      audioFromCompletionChunk({ audio: { url: '/api/digest/audio' } }),
    ).toEqual({ url: '/api/digest/audio' });
  });

  it('returns undefined for an ordinary reply', () => {
    expect(audioFromCompletionChunk({ usage: { total_tokens: 7 } })).toBeUndefined();
  });

  it('ignores an audio object without a usable url', () => {
    expect(audioFromCompletionChunk({ audio: {} })).toBeUndefined();
    expect(audioFromCompletionChunk({ audio: { url: '' } })).toBeUndefined();
    expect(audioFromCompletionChunk({ audio: { url: '   ' } })).toBeUndefined();
    expect(audioFromCompletionChunk({ audio: { url: 42 } })).toBeUndefined();
  });

  it('survives malformed chunks', () => {
    expect(audioFromCompletionChunk(undefined)).toBeUndefined();
    expect(audioFromCompletionChunk(null)).toBeUndefined();
    expect(audioFromCompletionChunk('nope')).toBeUndefined();
    expect(audioFromCompletionChunk({ audio: 'nope' })).toBeUndefined();
  });
});
