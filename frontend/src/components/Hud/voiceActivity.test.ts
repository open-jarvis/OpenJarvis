import { describe, expect, it } from 'vitest';
import { createVoiceActivity } from './voiceActivity';

/** Feed one level every 20 ms (like a 50 fps meter) and collect events. */
function run(vad: ReturnType<typeof createVoiceActivity>, levels: number[], start = 0) {
  const events: { t: number; e: string }[] = [];
  levels.forEach((level, i) => {
    const t = start + i * 20;
    const e = vad.update(level, t);
    if (e !== 'none') events.push({ t, e });
  });
  return events;
}

const repeat = (level: number, ms: number) => Array(Math.round(ms / 20)).fill(level);

describe('voice activity', () => {
  it('starts on speech and ends after a pause', () => {
    const vad = createVoiceActivity();
    const events = run(vad, [
      ...repeat(0.01, 600), // quiet room (calibration)
      ...repeat(0.4, 1000), // talking
      ...repeat(0.01, 1500), // pause
    ]);
    expect(events.map((x) => x.e)).toEqual(['speech-start', 'speech-end']);
    expect(vad.heardSpeech()).toBe(true);
  });

  it('does not end on a short breath between words', () => {
    const vad = createVoiceActivity({ silenceMs: 1100 });
    const events = run(vad, [
      ...repeat(0.01, 600),
      ...repeat(0.4, 600),
      ...repeat(0.01, 500), // short gap
      ...repeat(0.4, 600),
    ]);
    expect(events.map((x) => x.e)).toEqual(['speech-start']);
  });

  it('ignores a click or bump shorter than the start window', () => {
    const vad = createVoiceActivity();
    const events = run(vad, [...repeat(0.01, 600), 0.9, 0.9, ...repeat(0.01, 1000)]);
    expect(events).toEqual([]);
    expect(vad.heardSpeech()).toBe(false);
  });

  it('adapts to a noisy room instead of treating the noise as speech', () => {
    const vad = createVoiceActivity();
    const events = run(vad, [...repeat(0.12, 600), ...repeat(0.13, 3000)]);
    expect(events).toEqual([]);
  });

  it('still hears speech over that noise', () => {
    const vad = createVoiceActivity();
    const events = run(vad, [...repeat(0.12, 600), ...repeat(0.6, 800), ...repeat(0.12, 1500)]);
    expect(events.map((x) => x.e)).toEqual(['speech-start', 'speech-end']);
  });

  it('cuts off a very long utterance', () => {
    const vad = createVoiceActivity({ maxUtteranceMs: 2000 });
    const events = run(vad, [...repeat(0.01, 600), ...repeat(0.5, 3000)]);
    expect(events.map((x) => x.e)).toEqual(['speech-start', 'speech-end']);
  });

  it('reports a timeout after a long silence so the recording can restart', () => {
    const vad = createVoiceActivity({ idleTimeoutMs: 3000 });
    const events = run(vad, repeat(0.01, 4000));
    expect(events.map((x) => x.e)).toEqual(['timeout']);
  });
});
