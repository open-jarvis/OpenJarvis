import { describe, expect, it } from 'vitest';

import {
  kioskStateLabel,
  panelStatusLabel,
  shouldShimmerVoiceStatus,
  voiceStatusLabel,
  VOICE_UI_TEXT,
} from './voiceUiText';

describe('voice UI translations', () => {
  it('translates every Kiosk state', () => {
    expect(Object.keys(VOICE_UI_TEXT.vi.kioskState)).toEqual([
      'idle',
      'approaching',
      'prompting',
      'active',
      'cleanup',
    ]);
    expect(Object.values(VOICE_UI_TEXT.vi.kioskState)).toEqual([
      'Jarvis đang chờ khách',
      'Jarvis đang phát hiện có người',
      'Jarvis đang chờ xác nhận',
      'Jarvis đang trò chuyện',
      'Jarvis đang kết thúc phiên',
    ]);
    expect(Object.values(VOICE_UI_TEXT.en.kioskState)).toEqual([
      'Jarvis is idle waiting for a guest',
      'Jarvis is detecting someone',
      'Jarvis is waiting for confirmation',
      'Jarvis is in conversation',
      'Jarvis is wrapping up the session',
    ]);
    expect(kioskStateLabel('vi', 'active')).toBe('Jarvis đang trò chuyện');
    expect(kioskStateLabel('en', 'cleanup')).toBe('Jarvis is wrapping up the session');
  });

  it('translates every Voice status', () => {
    expect(Object.values(VOICE_UI_TEXT.vi.voiceStatus)).toEqual([
      'Jarvis đang chờ khách',
      'Kết nối',
      'Lắng nghe',
      'Nói',
      'Xử lý',
      'Xử lý',
      'Suy luận',
      'Tool',
      'Đã xảy ra lỗi giọng nói',
      'Đã kết thúc',
    ]);
    expect(Object.values(VOICE_UI_TEXT.en.voiceStatus)).toEqual([
      'Jarvis is idle waiting for a guest',
      'Connecting',
      'Listening',
      'Speaking',
      'Processing',
      'Processing',
      'Inference',
      'Tool',
      'Voice error',
      'Voice ended',
    ]);
    expect(voiceStatusLabel('vi', 'listening')).toBe('Lắng nghe...');
    expect(voiceStatusLabel('en', 'listening')).toBe('Listening...');
    expect(voiceStatusLabel('vi', 'error')).toBe('Đã xảy ra lỗi giọng nói');
    expect(voiceStatusLabel('en', 'ended')).toBe('Voice ended');
  });

  it('hides model details while preserving the literal tool name', () => {
    expect(voiceStatusLabel('vi', 'inference', 'deepseek-v4-flash'))
      .toBe('Suy luận...');
    expect(voiceStatusLabel('en', 'tool', 'browser_open'))
      .toBe('browser_open...');
  });

  it('localizes the selector labels, helper text, and compact voice badge', () => {
    expect(VOICE_UI_TEXT.vi.language).toEqual({ vietnamese: 'Tiếng Việt', english: 'English' });
    expect(VOICE_UI_TEXT.en.language).toEqual({ vietnamese: 'Vietnamese', english: 'English' });
    expect(VOICE_UI_TEXT.vi.languageHelper).toBe('Ngôn ngữ cho lớp phủ Kiosk và trạng thái Voice.');
    expect(VOICE_UI_TEXT.en.languageHelper).toBe('Language for Kiosk overlay and Voice status.');
    expect(panelStatusLabel('vi', 'thinking')).toBe('Đang xử lý');
    expect(panelStatusLabel('en', 'speaking')).toBe('Speaking');
  });

  it('shimmers speech, listening, and active pre-audio statuses', () => {
    expect(shouldShimmerVoiceStatus('connecting')).toBe(true);
    expect(shouldShimmerVoiceStatus('speaking')).toBe(true);
    expect(shouldShimmerVoiceStatus('listening')).toBe(true);
    expect(shouldShimmerVoiceStatus('processing')).toBe(true);
    expect(shouldShimmerVoiceStatus('inference')).toBe(true);
    expect(shouldShimmerVoiceStatus('tool')).toBe(true);
    expect(shouldShimmerVoiceStatus('busy')).toBe(true);
  });
});
