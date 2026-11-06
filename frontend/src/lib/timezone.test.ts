import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  TIMEZONE_HEADER,
  deviceTimeZone,
  isValidTimeZone,
  resolveTimeZone,
  timeZoneHeaders,
  utcOffsetLabel,
} from './timezone';

// Minimal in-memory localStorage, as in api.auth.test.ts.
beforeEach(() => {
  const data = new Map<string, string>();
  (globalThis as unknown as { localStorage: Pick<Storage, 'getItem' | 'setItem'> }).localStorage = {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, String(v)),
  };
});
afterEach(() => {
  delete (globalThis as unknown as { localStorage?: unknown }).localStorage;
});

describe('user time zone', () => {
  it('uses the device zone unless Settings picks one', () => {
    expect(resolveTimeZone('')).toBe(deviceTimeZone());
    expect(resolveTimeZone('Africa/Cairo')).toBe('Africa/Cairo');
    expect(resolveTimeZone('Not/AZone')).toBe(deviceTimeZone());
    expect(isValidTimeZone('Asia/Tokyo')).toBe(true);
  });

  it('labels the UTC offset', () => {
    expect(utcOffsetLabel('Asia/Tokyo')).toBe('UTC+09:00');
    expect(utcOffsetLabel('UTC')).toBe('UTC+00:00');
  });

  it('sends the device zone, or the one picked in Settings', () => {
    expect(timeZoneHeaders()).toEqual({ [TIMEZONE_HEADER]: deviceTimeZone() });
    localStorage.setItem('openjarvis-settings', JSON.stringify({ timeZone: 'Africa/Cairo' }));
    expect(timeZoneHeaders()).toEqual({ [TIMEZONE_HEADER]: 'Africa/Cairo' });
  });
});
