import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { preloadModel } from './api';

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('cloud model selection', () => {
  it.each([
    'cheaperinference/gpt-5.4-mini',
    'cheaperinference/claude-sonnet-5',
    'cheaperinference/gemini-3.1-pro',
  ])('does not send %s to the local Ollama preload endpoint', async (model) => {
    fetchMock.mockRejectedValue(new Error('Unexpected local model preload'));
    await expect(preloadModel(model)).resolves.toBeUndefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('still preloads a local model', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    await preloadModel('qwen3.5:4b');
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, request] = fetchMock.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:11434/api/generate');
    expect(JSON.parse(request!.body as string).model).toBe('qwen3.5:4b');
  });
});
