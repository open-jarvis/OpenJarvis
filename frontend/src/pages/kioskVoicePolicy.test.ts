import { describe, expect, it } from 'vitest';

import { kioskVoiceCommand } from './kioskVoicePolicy';

describe('kioskVoiceCommand', () => {
  it('starts only when the policy grants mic access', () => {
    expect(kioskVoiceCommand({ micEnabled: true, voiceEnabled: true, owner: null })).toBe('start');
  });

  it('ends a policy-started session when policy revokes access', () => {
    expect(kioskVoiceCommand({ micEnabled: false, voiceEnabled: true, owner: 'policy' })).toBe('end');
  });

  it('does not end a manually started session when policy mic access is off', () => {
    expect(kioskVoiceCommand({
      micEnabled: false,
      voiceEnabled: true,
      owner: 'manual',
    })).toBe('noop');
  });

  it('reports unavailable when Voice cannot start', () => {
    expect(kioskVoiceCommand({ micEnabled: true, voiceEnabled: false, owner: null })).toBe('unavailable');
  });

  it('does not duplicate an active start', () => {
    expect(kioskVoiceCommand({ micEnabled: true, voiceEnabled: true, owner: 'policy' })).toBe('noop');
  });
});
