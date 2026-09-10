import { describe, expect, it } from 'vitest';

import {
  assistantCaptionDelta,
  currentVoiceTurnRows,
  nextCaptionSegment,
  partitionCaptionSegments,
  splitCaptionSegments,
  voiceCaptionHoldMs,
} from './voiceTurnRows';

describe('currentVoiceTurnRows', () => {
  it('keeps user speech, assistant reply, and failure text separate', () => {
    expect(currentVoiceTurnRows({
      transcript: 'Xin chao',
      assistantText: 'Chao ban',
      error: 'transcript_empty',
    })).toEqual([
      { role: 'error', text: 'transcript_empty' },
      { role: 'user', text: 'Xin chao' },
      { role: 'assistant', text: 'Chao ban' },
    ]);
  });
});

describe('assistant caption timeline', () => {
  it('extracts only newly committed spoken text from cumulative partials', () => {
    expect(assistantCaptionDelta('Đầu tiên.', 'Đầu tiên. Sau đó.')).toBe('Sau đó.');
  });

  it('rejects a transcript revision that cannot be aligned safely', () => {
    expect(assistantCaptionDelta('Đầu tiên.', 'Nội dung khác.')).toBe('');
  });

  it('advances the caption only when an audio segment starts', () => {
    expect(nextCaptionSegment(['Đoạn một.', 'Đoạn hai.'], '')).toEqual({
      pending: ['Đoạn hai.'],
      current: 'Đoạn một.',
    });
  });

  it('keeps the current caption when audio has no pending text', () => {
    expect(nextCaptionSegment([], 'Đoạn đang phát.')).toEqual({
      pending: [],
      current: 'Đoạn đang phát.',
    });
  });

  it('holds a caption briefly so split PCM frames cannot reveal the next phrase', () => {
    expect(nextCaptionSegment(['Đoạn sau.'], 'Đoạn đang phát.', 400, 900)).toEqual({
      pending: ['Đoạn sau.'],
      current: 'Đoạn đang phát.',
    });
  });

  it('splits a long speech segment into sentence captions', () => {
    expect(splitCaptionSegments('Đoạn đầu. Đoạn sau!')).toEqual([
      'Đoạn đầu.',
      'Đoạn sau!',
    ]);
  });

  it('estimates longer caption holds from spoken text length', () => {
    expect(voiceCaptionHoldMs('Ngắn.')).toBe(900);
    expect(voiceCaptionHoldMs('x'.repeat(40))).toBe(2600);
  });
});

describe('partitionCaptionSegments', () => {
  it('handles empty or whitespace strings', () => {
    expect(partitionCaptionSegments('')).toEqual({ completedText: '', activeText: '' });
    expect(partitionCaptionSegments('   ')).toEqual({ completedText: '', activeText: '' });
  });

  it('keeps single sentence as purely active text', () => {
    expect(partitionCaptionSegments('Xin chào quý khách!')).toEqual({
      completedText: '',
      activeText: 'Xin chào quý khách!',
    });
  });

  it('partitions multiple sentences into completed and active segments', () => {
    expect(partitionCaptionSegments('Xin chào quý khách. Tôi có thể giúp gì cho bạn?')).toEqual({
      completedText: 'Xin chào quý khách.',
      activeText: 'Tôi có thể giúp gì cho bạn?',
    });
  });

  it('handles trailing spaces and three sentences properly', () => {
    expect(partitionCaptionSegments('Một. Hai! Ba? ')).toEqual({
      completedText: 'Một. Hai!',
      activeText: 'Ba?',
    });
  });
});

