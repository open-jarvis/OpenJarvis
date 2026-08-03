import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { synthesizeSpeech } from './api';
import {
  DisabledSpeechToTextProvider,
  LocalTextToSpeechProvider,
  LOCAL_AUDIO_END_EVENT,
  LOCAL_AUDIO_LEVEL_EVENT,
  LOCAL_AUDIO_START_EVENT,
  sentenceChunks,
} from './speechProviders';

vi.mock('./api', () => ({
  synthesizeSpeech: vi.fn(),
  transcribeAudio: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(synthesizeSpeech).mockReset().mockResolvedValue({
    audio: new Blob(['RIFF']),
    backend: 'chatterbox',
    fallbackUsed: false,
    cacheHit: false,
    synthesisMs: 5,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('speech provider boundaries', () => {
  it('bounds long clauses so the first local audio starts promptly', () => {
    const chunks = sentenceChunks(
      'Ich habe deine umfangreiche Anfrage vollständig analysiert, und bereite jetzt die wichtigsten Ergebnisse in einer klaren Reihenfolge auf, damit du nicht auf einen einzigen sehr langen Sprachblock warten musst.',
    );

    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((chunk) => chunk.length <= 110)).toBe(true);
    expect(chunks.join(' ').replace(/\s+/g, ' ')).toContain('sehr langen Sprachblock');
  });

  it('keeps disabled speech explicitly unavailable', async () => {
    const provider = new DisabledSpeechToTextProvider();
    expect(provider.available).toBe(false);
    await expect(provider.start()).rejects.toThrow('disabled');
  });

  it('aborts local sentence streaming and emits the shared playback end event', () => {
    const abort = vi.spyOn(AbortController.prototype, 'abort');
    const dispatch = vi.fn();
    vi.stubGlobal('window', { dispatchEvent: dispatch });
    vi.stubGlobal('Audio', class {});
    const provider = new LocalTextToSpeechProvider('chatterbox+piper', true);
    expect(provider.available).toBe(true);
    provider.speak('Erster Satz. Zweiter Satz.', 'de-DE', vi.fn(), vi.fn());
    provider.stop();
    expect(abort).toHaveBeenCalled();
    expect(dispatch.mock.calls.some(([event]) => event.type === LOCAL_AUDIO_END_EVENT)).toBe(true);
  });

  it('prefetches sentence chunks and emits one measured start/end pair', async () => {
    const dispatch = vi.fn();
    const createObjectURL = vi.fn(() => 'blob:voice');
    const revokeObjectURL = vi.fn();
    class FakeAudio {
      onplay: (() => void) | null = null;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      paused = false;
      ended = false;

      constructor(public src: string) {}

      play(): Promise<void> {
        this.onplay?.();
        queueMicrotask(() => {
          this.ended = true;
          this.onended?.();
        });
        return Promise.resolve();
      }

      pause(): void {
        this.paused = true;
      }
    }
    vi.stubGlobal('window', { dispatchEvent: dispatch, AudioContext: undefined });
    vi.stubGlobal('Audio', FakeAudio);
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });

    const provider = new LocalTextToSpeechProvider('chatterbox+piper', true);
    await new Promise<void>((resolve, reject) => {
      provider.speak('Erster Satz. Zweiter Satz.', 'de-DE', resolve, reject);
    });

    expect(vi.mocked(synthesizeSpeech).mock.calls.map(([text]) => text)).toEqual([
      'Erster Satz.',
      'Zweiter Satz.',
    ]);
    const startEvents = dispatch.mock.calls
      .map(([event]) => event)
      .filter((event) => event.type === LOCAL_AUDIO_START_EVENT);
    const endEvents = dispatch.mock.calls
      .map(([event]) => event)
      .filter((event) => event.type === LOCAL_AUDIO_END_EVENT);
    expect(startEvents).toHaveLength(1);
    expect(startEvents[0].detail.backend).toBe('chatterbox');
    expect(startEvents[0].detail.requestToPlaybackMs).toBeGreaterThanOrEqual(0);
    expect(endEvents).toHaveLength(1);
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it('emits a bounded, audible waveform level for the star/core consumer', async () => {
    const dispatch = vi.fn();
    class FakeAudioContext {
      destination = {};
      createAnalyser() {
        return {
          fftSize: 256,
          connect: vi.fn(),
          getByteTimeDomainData: (values: Uint8Array) => values.fill(160),
        };
      }
      createMediaElementSource() { return { connect: vi.fn() }; }
      close() { return Promise.resolve(); }
    }
    class FakeAudio {
      onplay: (() => void) | null = null;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      paused = false;
      ended = false;
      constructor(public src: string) {}
      play() {
        this.onplay?.();
        this.ended = true;
        this.onended?.();
        return Promise.resolve();
      }
      pause() { this.paused = true; }
    }
    vi.stubGlobal('window', { dispatchEvent: dispatch, AudioContext: FakeAudioContext });
    vi.stubGlobal('Audio', FakeAudio);
    vi.stubGlobal('URL', { createObjectURL: () => 'blob:voice', revokeObjectURL: vi.fn() });
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());

    const provider = new LocalTextToSpeechProvider('chatterbox+piper', true);
    await new Promise<void>((resolve, reject) => provider.speak('Test.', 'de-DE', resolve, reject));
    const levelEvent = dispatch.mock.calls
      .map(([event]) => event)
      .find((event) => event.type === LOCAL_AUDIO_LEVEL_EVENT);
    expect(levelEvent).toBeDefined();
    expect(levelEvent.detail.level).toBeGreaterThan(0.16);
    expect(levelEvent.detail.level).toBeLessThanOrEqual(1);
  });
});
