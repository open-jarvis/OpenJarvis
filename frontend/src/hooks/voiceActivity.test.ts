import { describe, expect, it } from 'vitest';

import { voiceActivityFromServerMessage } from './voiceActivity';

describe('voiceActivityFromServerMessage', () => {
  it('accepts only the allowlisted activity fields', () => {
    expect(
      voiceActivityFromServerMessage({
        data: {
          type: 'voice_activity',
          phase: 'inference',
          model: 'deepseek-v4-flash',
          arguments: { secret: 'no' },
        },
      }),
    ).toEqual({ phase: 'inference', model: 'deepseek-v4-flash' });
    expect(
      voiceActivityFromServerMessage({
        data: {
          type: 'voice_activity',
          phase: 'tool',
          tool_name: 'browser_open',
          result: 'private',
        },
      }),
    ).toEqual({ phase: 'tool', toolName: 'browser_open' });
  });

  it('rejects invalid phases and incomplete details', () => {
    expect(
      voiceActivityFromServerMessage({
        data: { type: 'voice_activity', phase: 'tool' },
      }),
    ).toBeNull();
    expect(
      voiceActivityFromServerMessage({
        data: { type: 'voice_activity', phase: 'inference', model: 42 },
      }),
    ).toBeNull();
    expect(
      voiceActivityFromServerMessage({
        data: { type: 'other', phase: 'tool', tool_name: 'browser_open' },
      }),
    ).toBeNull();
  });
});
