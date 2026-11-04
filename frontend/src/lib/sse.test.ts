import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SSEEvent } from '../types';

vi.mock('./api', () => ({
  authHeaders: (headers: Record<string, string> = {}) => headers,
  getBase: () => '',
}));

import { streamChat } from './sse';

const request = {
  model: 'gpt-4o-mini',
  messages: [{ role: 'user', content: 'Hello' }],
  stream: true as const,
};

async function firstChatEvent(): Promise<void> {
  for await (const _event of streamChat(request)) {
    break;
  }
}

describe('streamChat', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('includes server error detail in failed chat requests', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'OPENAI_API_KEY is not configured' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(firstChatEvent()).rejects.toThrow(
      'Chat request failed: 400: OPENAI_API_KEY is not configured',
    );
  });

  it('uses a nested provider error message when the API returns one', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { message: 'Invalid API key' } }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(firstChatEvent()).rejects.toThrow(
      'Chat request failed: 401: Invalid API key',
    );
  });

  it('falls back to the status when an error body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('upstream unavailable', { status: 502 })),
    );

    await expect(firstChatEvent()).rejects.toThrow('Chat request failed: 502');
  });

  it('reports an empty successful response instead of crashing on a missing body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );

    await expect(firstChatEvent()).rejects.toThrow(
      'Chat request failed: the server returned an empty response.',
    );
  });

  it('continues yielding successful streaming events', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n',
          { status: 200 },
        ),
      ),
    );

    const events: SSEEvent[] = [];
    for await (const event of streamChat(request)) events.push(event);
    expect(events).toEqual([
      { event: undefined, data: '{"choices":[{"delta":{"content":"Hello"}}]}' },
    ]);
  });
});
