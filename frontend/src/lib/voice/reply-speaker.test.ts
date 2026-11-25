import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReplySpeaker } from './reply-speaker';

/** Minimal HTMLAudioElement stand-in: "plays" until ended() or pause(). */
class FakeAudio {
  static instances: FakeAudio[] = [];
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  paused = true;
  constructor(public src: string) {
    FakeAudio.instances.push(this);
  }
  play() {
    this.paused = false;
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
  }
  finish() {
    this.paused = true;
    this.onended?.();
  }
}

const tick = () => new Promise((r) => setTimeout(r, 0));

describe('ReplySpeaker', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeAudio.instances = [];
  });

  it('plays every chunk in order', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    const synthesize = vi.fn(async () => new Blob(['x']));
    const speaker = new ReplySpeaker({ synthesize });
    const text = 'This is the first sentence of the reply. This is the second sentence of the reply.';
    const done = speaker.speak(text);
    for (let i = 0; i < 2; i++) {
      await tick();
      await tick();
      FakeAudio.instances[i].finish();
    }
    await done;
    expect(synthesize).toHaveBeenCalledTimes(2);
    expect(FakeAudio.instances).toHaveLength(2);
  });

  it('cancel() silences the clip that is playing (regression: it kept playing)', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    const speaker = new ReplySpeaker({ synthesize: async () => new Blob(['x']) });
    const done = speaker.speak('A reply long enough to be spoken in one single chunk of audio.');
    await tick();
    await tick();
    const playing = FakeAudio.instances[0];
    expect(playing.paused).toBe(false);
    speaker.cancel();
    expect(playing.paused).toBe(true);
    await done;
    expect(speaker.speaking).toBe(false);
  });
});
