// Polyfills for browser APIs that only exist in a "secure context" (HTTPS or localhost).
//
// The UI can be reached over plain HTTP on a LAN (e.g. http://192.168.x.x:8000 from a phone),
// where `crypto.randomUUID` is undefined. `store.ts` calls it while the module is being
// evaluated, so without this the whole page stays blank with
// "TypeError: crypto.randomUUID is not a function".
// `crypto.getRandomValues` is available in insecure contexts, so build a v4 UUID from it.

export function ensureRandomUUID(c: Crypto | undefined = globalThis.crypto): void {
  if (!c || typeof c.randomUUID === 'function') return;
  const uuid = (): `${string}-${string}-${string}-${string}-${string}` => {
    const b = new Uint8Array(16);
    c.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40; // version 4
    b[8] = (b[8] & 0x3f) | 0x80; // variant 10xx
    const h = Array.from(b, (x) => x.toString(16).padStart(2, '0'));
    return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10).join('')}`;
  };
  Object.defineProperty(c, 'randomUUID', { value: uuid, configurable: true, writable: true });
}

ensureRandomUUID();
