import { describe, expect, it } from 'vitest';

import { kioskVoiceCommand } from './kioskVoicePolicy';

describe('kioskVoiceCommand', () => {
  it('starts only when the policy grants mic access', () => {
    expect(kioskVoiceCommand({ micEnabled: true, voiceEnabled: true, started: false })).toBe('start');
  });

  it('ends the active native session when policy revokes access', () => {
    expect(kioskVoiceCommand({ micEnabled: false, voiceEnabled: true, started: true })).toBe('end');
  });

  it('reports unavailable when Voice cannot start', () => {
    expect(kioskVoiceCommand({ micEnabled: true, voiceEnabled: false, started: false })).toBe('unavailable');
  });

  it('does not duplicate an active start', () => {
    expect(kioskVoiceCommand({ micEnabled: true, voiceEnabled: true, started: true })).toBe('noop');
  });
});
