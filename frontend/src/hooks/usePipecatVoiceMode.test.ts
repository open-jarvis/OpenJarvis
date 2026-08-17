import { describe, expect, it } from 'vitest';

import {
  botStoppedSpeaking,
  hasAudibleSpectrum,
  voiceAvailability,
  voiceStatusForActivity,
  voiceStatusForError,
} from './usePipecatVoiceMode';
import { voiceTurnMessage } from './usePipecatVoiceMode';

describe('voiceStatusForError', () => {
  it('reads a refused lease as busy, not as a failure', () => {
    // The server answers 409 when another Voice session holds the lease, and
    // the caller is meant to fall back to text rather than show an error.
    expect(voiceStatusForError({ status: 409 })).toBe('busy');
  });

  it('treats every other failure as an error', () => {
    expect(voiceStatusForError({ status: 503 })).toBe('error');
    expect(voiceStatusForError(new Error('ice failed'))).toBe('error');
    expect(voiceStatusForError(undefined)).toBe('error');
  });
});

describe('voiceAvailability', () => {
  it('enables voice when the server says the runtime is up', () => {
    expect(voiceAvailability({ gemini_live_enabled: true })).toEqual({
      enabled: true,
      unavailableReason: null,
    });
  });

  it('carries the server reason when voice is off', () => {
    expect(
      voiceAvailability({ gemini_live_enabled: false, gemini_live_reason: 'poc_auth_required' }),
    ).toEqual({ enabled: false, unavailableReason: 'poc_auth_required' });
  });

  it('falls back to a reason of its own when the server gives none', () => {
    expect(voiceAvailability({ gemini_live_enabled: false })).toEqual({
      enabled: false,
      unavailableReason: 'poc_disabled',
    });
  });
});

describe('hasAudibleSpectrum', () => {
  it('is quiet when the bins are near zero', () => {
    expect(hasAudibleSpectrum(new Uint8Array(128))).toBe(false);
  });

  it('is audible once the bins carry energy', () => {
    expect(hasAudibleSpectrum(new Uint8Array(128).fill(40))).toBe(true);
  });
});

describe('voiceTurnMessage', () => {
  it('builds a chat message from a finished turn', () => {
    const message = voiceTurnMessage('user', 'mở YouTube giúp tôi');

    expect(message).toMatchObject({ role: 'user', content: 'mở YouTube giúp tôi' });
    expect(message?.id).toBeTruthy();
    expect(typeof message?.timestamp).toBe('number');
  });

  it('drops a blank turn', () => {
    // Barge-in can end an assistant turn before a single word is spoken.
    expect(voiceTurnMessage('assistant', '')).toBeNull();
    expect(voiceTurnMessage('assistant', '   ')).toBeNull();
  });

  it('trims what it stores', () => {
    expect(voiceTurnMessage('assistant', '  Đã mở rồi.  ')?.content).toBe('Đã mở rồi.');
  });
});

describe('botStoppedSpeaking', () => {
  it('clears the caption after emitting a turn', () => {
    // BotStoppedSpeaking fires on a TTS idle timeout, and a tool call mid-answer
    // routinely exceeds it — "Đang mở YouTube…" [browser tool] "…xong rồi" is a
    // single turn split across two BotStoppedSpeaking events. If the caption is
    // not cleared here, the next chunk is appended to what was already emitted
    // and the same answer is written to the sidebar again, longer each time.
    const first = botStoppedSpeaking('Đang mở YouTube…');
    expect(first.message).toMatchObject({ role: 'assistant', content: 'Đang mở YouTube…' });
    expect(first.nextCaption).toBe('');
  });

  it('emits nothing for a blank caption and still resets', () => {
    const result = botStoppedSpeaking('   ');
    expect(result.message).toBeNull();
    expect(result.nextCaption).toBe('');
  });
});

describe('voiceStatusForActivity', () => {
  it('maps only protocol evidence to visible active statuses', () => {
    expect(voiceStatusForActivity({ phase: 'processing' })).toEqual({
      status: 'processing',
      detail: null,
    });
    expect(voiceStatusForActivity({ phase: 'inference', model: 'deepseek-v4-flash' })).toEqual({
      status: 'inference',
      detail: 'deepseek-v4-flash',
    });
    expect(voiceStatusForActivity({ phase: 'tool', toolName: 'browser_open' })).toEqual({
      status: 'tool',
      detail: 'browser_open',
    });
  });
});
