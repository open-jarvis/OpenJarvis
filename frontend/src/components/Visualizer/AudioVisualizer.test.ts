import { describe, expect, it } from 'vitest';

import { startRenderLoop } from './AudioVisualizer';

/** Drives queued frame callbacks by hand so no real rAF/DOM is needed. */
function fakeRaf() {
  let next = 1;
  let queue: Array<{ handle: number; cb: () => void }> = [];
  const cancelled = new Set<number>();
  return {
    raf: (cb: () => void) => {
      const handle = next++;
      queue.push({ handle, cb });
      return handle;
    },
    cancel: (handle: number) => cancelled.add(handle),
    /** Run everything queued for one frame; returns how many ran. */
    flush() {
      const due = queue.filter((f) => !cancelled.has(f.handle));
      queue = [];
      due.forEach((f) => f.cb());
      return due.length;
    },
    get pending() {
      return queue.filter((f) => !cancelled.has(f.handle)).length;
    },
  };
}

describe('startRenderLoop', () => {
  it('keeps exactly one frame pending, never doubling', () => {
    const t = fakeRaf();
    let draws = 0;
    startRenderLoop(() => { draws++; }, t.raf, t.cancel);

    // The regression: pending used to go 1, 2, 4, 8, ... per frame.
    for (let frame = 0; frame < 12; frame++) {
      expect(t.pending).toBe(1);
      expect(t.flush()).toBe(1);
    }
    expect(draws).toBe(12);
  });

  it('keeps one frame pending even when draw() returns early', () => {
    const t = fakeRaf();
    // Mirrors the tiny-canvas branch that used to schedule a second frame.
    startRenderLoop(() => { return; }, t.raf, t.cancel);
    for (let frame = 0; frame < 8; frame++) {
      expect(t.flush()).toBe(1);
    }
    expect(t.pending).toBe(1);
  });

  it('stops scheduling and stops drawing after stop()', () => {
    const t = fakeRaf();
    let draws = 0;
    const stop = startRenderLoop(() => { draws++; }, t.raf, t.cancel);

    t.flush();
    expect(draws).toBe(1);

    stop();
    expect(t.pending).toBe(0);
    t.flush();
    expect(draws).toBe(1);
  });

  it('survives stop() called twice', () => {
    const t = fakeRaf();
    const stop = startRenderLoop(() => {}, t.raf, t.cancel);
    stop();
    expect(() => stop()).not.toThrow();
    expect(t.pending).toBe(0);
  });
});
