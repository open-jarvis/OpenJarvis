import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ALL_AGENTS, buildWsUrl, shouldSubscribe } from './useAgentEvents';

// `/v1/agents/events` has always broadcast every agent's events — `agent_id`
// is an optional server-side filter. Only this hook prevented a global feed,
// by refusing to connect without an id. These cover the pure helpers behind
// that decision, in the style of api.auth.test.ts (no jsdom in this suite).

// The helper reads `window.location`; there is no window under node.
const g = globalThis as unknown as { window?: unknown };
const originalWindow = g.window;

function setPage(protocol: string, host: string): void {
  g.window = { location: { protocol, host } };
}

beforeEach(() => {
  setPage('http:', 'localhost:5173');
});

afterEach(() => {
  g.window = originalWindow;
});

describe('shouldSubscribe', () => {
  it('does not subscribe without an id', () => {
    // Callers pass a possibly-undefined selected-agent id and rely on this
    // meaning "do not subscribe". Changing it would turn every such caller
    // into a firehose subscription.
    expect(shouldSubscribe(undefined)).toBe(false);
    expect(shouldSubscribe('')).toBe(false);
  });

  it('subscribes for a single agent', () => {
    expect(shouldSubscribe('1183a1b037e7')).toBe(true);
  });

  it('subscribes for ALL_AGENTS', () => {
    expect(shouldSubscribe(ALL_AGENTS)).toBe(true);
  });
});

describe('buildWsUrl', () => {
  it('filters to one agent', () => {
    expect(buildWsUrl('1183a1b037e7')).toBe(
      'ws://localhost:5173/v1/agents/events?agent_id=1183a1b037e7',
    );
  });

  it('sends no filter for ALL_AGENTS', () => {
    // Sending agent_id=* would filter for an agent literally named "*",
    // which matches nothing — the absence of the parameter is the filter.
    expect(buildWsUrl(ALL_AGENTS)).toBe('ws://localhost:5173/v1/agents/events');
    expect(buildWsUrl(ALL_AGENTS)).not.toContain('agent_id');
  });

  it('sends no filter when no id is given', () => {
    expect(buildWsUrl()).toBe('ws://localhost:5173/v1/agents/events');
  });

  it('escapes an id so it cannot alter the query', () => {
    expect(buildWsUrl('a&b=c')).toBe(
      'ws://localhost:5173/v1/agents/events?agent_id=a%26b%3Dc',
    );
  });

  it('upgrades wss for an https page', () => {
    setPage('https:', 'jarvis.local');
    expect(buildWsUrl(ALL_AGENTS)).toBe('wss://jarvis.local/v1/agents/events');
  });
});
