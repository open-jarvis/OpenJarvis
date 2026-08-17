import { describe, expect, it } from 'vitest';

import { applyKioskStateEvent } from './useKioskState';

describe('applyKioskStateEvent', () => {
  it('enables the microphone only from an explicit active policy event', () => {
    expect(applyKioskStateEvent(
      { state: 'active', micEnabled: false },
      { type: 'kiosk_state_changed', data: { state: 'active', mic_enabled: true } },
    )).toEqual({ state: 'active', micEnabled: true });
  });

  it('fails closed when mic_enabled is missing', () => {
    expect(applyKioskStateEvent(
      { state: 'active', micEnabled: true },
      { type: 'kiosk_state_changed', data: { state: 'active' } },
    )).toEqual({ state: 'active', micEnabled: false });
  });

  it('ignores malformed and unrelated events', () => {
    const current = { state: 'prompting' as const, micEnabled: false };
    expect(applyKioskStateEvent(current, { type: 'other', data: { state: 'active', mic_enabled: true } })).toBe(current);
    expect(applyKioskStateEvent(current, { type: 'kiosk_state_changed', data: { state: 'invalid', mic_enabled: true } })).toBe(current);
  });
});
