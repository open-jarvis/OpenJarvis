import { describe, expect, it } from 'vitest';
import { ensureRandomUUID } from './polyfills';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('ensureRandomUUID', () => {
  it('adds a v4 randomUUID when the context is insecure (no crypto.randomUUID)', () => {
    const fake = {
      getRandomValues: (a: Uint8Array) => {
        for (let i = 0; i < a.length; i++) a[i] = (i * 37 + 11) & 0xff;
        return a;
      },
    } as unknown as Crypto;
    expect(typeof fake.randomUUID).toBe('undefined');
    ensureRandomUUID(fake);
    expect(fake.randomUUID()).toMatch(UUID_V4);
  });

  it('generates different values with real randomness', () => {
    const real = {
      getRandomValues: (a: Uint8Array<ArrayBuffer>) => globalThis.crypto.getRandomValues(a),
    } as unknown as Crypto;
    ensureRandomUUID(real);
    const ids = new Set(Array.from({ length: 50 }, () => real.randomUUID()));
    expect(ids.size).toBe(50);
    ids.forEach((id) => expect(id).toMatch(UUID_V4));
  });

  it('does not replace an existing randomUUID', () => {
    const original = () => '00000000-0000-4000-8000-000000000000' as ReturnType<Crypto['randomUUID']>;
    const secure = { randomUUID: original, getRandomValues: () => new Uint8Array(0) } as unknown as Crypto;
    ensureRandomUUID(secure);
    expect(secure.randomUUID).toBe(original);
  });
});
