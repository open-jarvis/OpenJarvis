import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BrowserSpeechToTextProvider,
  BrowserTextToSpeechProvider,
  DisabledSpeechToTextProvider,
} from './speechProviders';

class FakeRecognition {
  static instance: FakeRecognition | null = null;
  lang = '';
  continuous = false;
  interimResults = false;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  started = false;
  aborted = false;

  constructor() { FakeRecognition.instance = this; }
  start() { this.started = true; }
  stop() { this.onend?.(); }
  abort() { this.aborted = true; }
}

afterEach(() => {
  vi.unstubAllGlobals();
  FakeRecognition.instance = null;
});

describe('speech provider boundaries', () => {
  it('keeps disabled speech explicitly unavailable', async () => {
    const provider = new DisabledSpeechToTextProvider();
    expect(provider.available).toBe(false);
    await expect(provider.start()).rejects.toThrow('disabled');
  });

  it('starts and stops browser push-to-talk without persisting audio', async () => {
    vi.stubGlobal('window', { SpeechRecognition: FakeRecognition });
    const provider = new BrowserSpeechToTextProvider();
    expect(provider.available).toBe(true);
    await provider.start('de-DE');
    const recognition = FakeRecognition.instance!;
    expect(recognition.lang).toBe('de-DE');
    recognition.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: 'Hallo Jarvis' } }],
    });
    await expect(provider.stop()).resolves.toBe('Hallo Jarvis');
    expect(Object.keys(provider).join(' ')).not.toContain('Blob');
  });

  it('starts and cancels browser TTS for barge-in', () => {
    const speak = vi.fn();
    const cancel = vi.fn();
    vi.stubGlobal('SpeechSynthesisUtterance', class {
      lang = '';
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public text: string) {}
    });
    vi.stubGlobal('window', { speechSynthesis: { speak, cancel } });
    const provider = new BrowserTextToSpeechProvider();
    provider.speak('Antwort', 'de-DE', vi.fn(), vi.fn());
    expect(speak).toHaveBeenCalledOnce();
    expect(cancel).toHaveBeenCalledOnce();
    provider.stop();
    expect(cancel).toHaveBeenCalledTimes(2);
  });
});
