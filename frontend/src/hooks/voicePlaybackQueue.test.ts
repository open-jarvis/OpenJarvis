import { describe, expect, it } from 'vitest';

import { VoicePlaybackQueue } from './voicePlaybackQueue';

class FakeAudio {
  onended: ((event: Event) => void) | null = null;
  paused = false;

  constructor(public src: string) {}

  play(): Promise<void> {
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }

  end(): void {
    this.onended?.(new Event('ended'));
  }
}

describe('VoicePlaybackQueue', () => {
  it('starts the first segment immediately and releases segments in order', () => {
    const audio: FakeAudio[] = [];
    const states: boolean[] = [];
    const started: string[] = [];
    const queue = new VoicePlaybackQueue(
      (src) => {
        const player = new FakeAudio(src);
        audio.push(player);
        return player;
      },
      (playing) => states.push(playing),
      undefined,
      (segment) => started.push(segment.text ?? ''),
    );

    queue.enqueue({ audio: 'first', mime: 'audio/mpeg' });
    queue.enqueue({ audio: 'second', mime: 'audio/mpeg' });

    expect(audio).toHaveLength(1);
    expect(audio[0].src).toBe('data:audio/mpeg;base64,first');
    audio[0].end();
    expect(audio[0].src).toBe('');
    expect(audio[1].src).toBe('data:audio/mpeg;base64,second');
    audio[1].end();

    expect(audio[1].src).toBe('');
    expect(states).toEqual([true, true, false]);
    expect(started).toEqual(['', '']);
  });

  it('reports the caption when a segment starts playing', () => {
    const started: string[] = [];
    const queue = new VoicePlaybackQueue(
      (src) => new FakeAudio(src),
      undefined,
      undefined,
      (segment) => started.push(segment.text ?? ''),
    );

    queue.enqueue({ audio: 'first', mime: 'audio/mpeg', text: 'Đoạn đang nói.' });

    expect(started).toEqual(['Đoạn đang nói.']);
  });

  it('stops current playback and clears queued segments immediately', () => {
    const audio: FakeAudio[] = [];
    const played: string[] = [];
    const queue = new VoicePlaybackQueue((src) => {
      const player = new FakeAudio(src);
      audio.push(player);
      return player;
    }, undefined, (segment) => played.push(segment.text ?? ''));

    queue.enqueue({ audio: 'first', mime: 'audio/mpeg', text: 'heard' });
    queue.enqueue({ audio: 'second', mime: 'audio/mpeg' });
    queue.stop();
    audio[0].end();

    expect(audio[0].paused).toBe(true);
    expect(audio[0].src).toBe('');
    expect(audio).toHaveLength(1);
    expect(played).toEqual([]);
  });
});
