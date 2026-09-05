import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  synthesizeSpeech: vi.fn(),
  fetchTtsHealth: vi.fn(),
}));

import { synthesizeSpeech, fetchTtsHealth } from './api';
import { useTtsStore, __resetTtsForTests } from './tts';

const synth = vi.mocked(synthesizeSpeech);
const health = vi.mocked(fetchTtsHealth);

/** Minimal HTMLAudioElement stand-in; jsdom cannot decode or play real audio. */
class FakeAudio {
  static instances: FakeAudio[] = [];
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src: string;
  paused = false;
  playCalls = 0;

  constructor(src: string) {
    this.src = src;
    FakeAudio.instances.push(this);
  }

  play(): Promise<void> {
    this.playCalls += 1;
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }
}

const created: string[] = [];
const revoked: string[] = [];
let urlCounter = 0;

beforeEach(() => {
  vi.stubGlobal('Audio', FakeAudio as unknown as typeof Audio);
  vi.stubGlobal('URL', {
    createObjectURL: () => {
      const url = `blob:fake/${++urlCounter}`;
      created.push(url);
      return url;
    },
    revokeObjectURL: (url: string) => {
      revoked.push(url);
    },
  });

  synth.mockReset();
  health.mockReset();

  // Reset the store first: it tears down whatever the previous test left
  // playing, and that teardown revokes a URL. Clearing the ledgers afterwards
  // keeps that bookkeeping out of this test's assertions.
  __resetTtsForTests();
  FakeAudio.instances = [];
  created.length = 0;
  revoked.length = 0;
  urlCounter = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('shared voice output', () => {
  it('plays one utterance and reports which message owns it', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Hallo');

    expect(FakeAudio.instances).toHaveLength(1);
    expect(FakeAudio.instances[0].playCalls).toBe(1);
    expect(useTtsStore.getState().state).toBe('speaking');
    expect(useTtsStore.getState().speakingId).toBe('m1');
  });

  it('starting a second message stops the first instead of overlapping it', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Erste');
    const first = FakeAudio.instances[0];

    await useTtsStore.getState().speak('m2', 'Zweite');

    expect(first.paused).toBe(true);
    expect(useTtsStore.getState().speakingId).toBe('m2');
    expect(revoked).toContain(created[0]);
  });

  it('aborts a synthesis that is superseded before it resolves', async () => {
    const pending = deferred<Blob>();
    synth.mockReturnValueOnce(pending.promise);
    synth.mockResolvedValueOnce(new Blob(['wav']));

    const firstCall = useTtsStore.getState().speak('m1', 'Erste');
    const signal = synth.mock.calls[0][1]?.signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    await useTtsStore.getState().speak('m2', 'Zweite');
    expect(signal.aborted).toBe(true);

    // The stale response must not start playback or leak its blob URL.
    pending.resolve(new Blob(['stale']));
    await firstCall;

    expect(FakeAudio.instances).toHaveLength(1);
    expect(useTtsStore.getState().speakingId).toBe('m2');
  });

  it('stop() halts playback and revokes the blob URL', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Hallo');
    useTtsStore.getState().stop();

    expect(FakeAudio.instances[0].paused).toBe(true);
    expect(revoked).toEqual(created);
    expect(useTtsStore.getState().state).toBe('idle');
    expect(useTtsStore.getState().speakingId).toBeNull();
  });

  it('finishing playback leaves no error behind', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Hallo');
    const el = FakeAudio.instances[0];

    el.onended?.();
    // Clearing src fires a media error; the handler must already be detached.
    el.onerror?.();

    expect(useTtsStore.getState().error).toBeNull();
    expect(useTtsStore.getState().state).toBe('idle');
    expect(revoked).toEqual(created);
  });

  it('surfaces a synthesis failure', async () => {
    synth.mockRejectedValue(new Error('No text-to-speech backend available'));

    await useTtsStore.getState().speak('m1', 'Hallo');

    expect(useTtsStore.getState().error).toBe('No text-to-speech backend available');
    expect(useTtsStore.getState().state).toBe('idle');
  });

  it('ignores empty text', async () => {
    await useTtsStore.getState().speak('m1', '   ');
    expect(synth).not.toHaveBeenCalled();
  });

  it('probes the backend once no matter how many callers ask', () => {
    health.mockResolvedValue({ available: true });

    useTtsStore.getState().ensureHealth();
    useTtsStore.getState().ensureHealth();
    useTtsStore.getState().ensureHealth();

    expect(health).toHaveBeenCalledTimes(1);
  });
});
