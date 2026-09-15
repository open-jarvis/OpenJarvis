import { describe, expect, it } from 'vitest';

import {
  botStoppedSpeaking,
  CAPTION_FADE_DURATION_MS,
  hasAudibleSpectrum,
  voiceAvailability,
  voiceErrorMessage,
  statusAfterUserStoppedSpeaking,
  voiceWebRtcRequestParams,
  voiceStatusForActivity,
  voiceStatusForError,
} from './usePipecatVoiceMode';
import { voiceTurnMessage } from './usePipecatVoiceMode';
import { SpeechPacer, voiceCaptionHoldMs } from '@/components/Chat/voiceTurnRows';

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

describe('voiceWebRtcRequestParams', () => {
  it('carries the configured API key on Pipecat offer and ICE requests', () => {
    const previousStorage = globalThis.localStorage;
    globalThis.localStorage = {
      getItem: () => JSON.stringify({ apiKey: 'oj_sk_voice_test' }),
    } as unknown as Storage;

    try {
      const request = voiceWebRtcRequestParams('thread-1', 'deepseek-v4-flash');
      expect(request.endpoint).toBe('/api/voice/webrtc/offer');
      expect(request.headers?.get('Authorization')).toBe('Bearer oj_sk_voice_test');
      expect(request.requestData).toEqual({
        chat_thread_id: 'thread-1',
        model: 'deepseek-v4-flash',
      });
    } finally {
      globalThis.localStorage = previousStorage;
    }
  });
});

describe('voiceErrorMessage', () => {
  it('never renders an absent transport failure as undefined', () => {
    expect(voiceErrorMessage(undefined)).toBe('voice_connection_failed');
    expect(voiceErrorMessage(null)).toBe('voice_connection_failed');
  });

  it('keeps a useful transport error message', () => {
    expect(voiceErrorMessage(new Error('HTTP 401'))).toBe('HTTP 401');
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

describe('statusAfterUserStoppedSpeaking', () => {
  it('keeps a server phase that arrived before the client event', () => {
    expect(statusAfterUserStoppedSpeaking('inference')).toBe('inference');
    expect(statusAfterUserStoppedSpeaking('tool')).toBe('tool');
  });

  it('shows processing when no server phase has arrived yet', () => {
    expect(statusAfterUserStoppedSpeaking('listening')).toBe('processing');
    expect(statusAfterUserStoppedSpeaking('speaking')).toBe('processing');
  });
});

describe('caption hold duration calculation', () => {
  it('keeps caption for proportional duration', () => {
    expect(voiceCaptionHoldMs('Chào bạn')).toBeGreaterThanOrEqual(900);
    expect(voiceCaptionHoldMs('Một câu văn bản dài hơn đáng kể cho khách đọc.')).toBeGreaterThan(1500);
  });

  it('bounds caption hold between minimum and maximum limits', () => {
    expect(voiceCaptionHoldMs('')).toBe(900);
    expect(voiceCaptionHoldMs('a'.repeat(10))).toBe(900);
    expect(voiceCaptionHoldMs('a'.repeat(200))).toBe(5000);
  });

  it('defines the standard 400ms fade duration', () => {
    expect(CAPTION_FADE_DURATION_MS).toBe(400);
  });
});

describe('assistant speech pacing & synchronization', () => {
  it('paces words sequentially and flushes remaining tokens on demand', () => {
    const emitted: string[] = [];
    const pacer = new SpeechPacer((token) => emitted.push(token));

    // Bot delivers sentence at t=0
    pacer.enqueue('Dạ em đã mở menu cà phê nhé!');
    // First token emitted immediately
    expect(emitted).toEqual(['Dạ ']);
    expect(pacer.isBusy()).toBe(true);

    // If audio ends before all tokens tick, flush returns the rest immediately
    const flushed = pacer.flush();
    expect(flushed).toBe('em đã mở menu cà phê nhé!');
    expect(pacer.isBusy()).toBe(false);
  });

  it('cancels pending words immediately when customer interrupts', () => {
    const emitted: string[] = [];
    const pacer = new SpeechPacer((token) => emitted.push(token));

    pacer.enqueue('Dạ đây là thông tin chi tiết đơn hàng.');
    expect(emitted).toEqual(['Dạ ']);

    // Customer barges in
    pacer.cancel();
    expect(pacer.isBusy()).toBe(false);
    expect(pacer.flush()).toBe('');
  });
});
