import { describe, expect, it } from 'vitest';
import { UtteranceDetector } from './utterance-detector';
import { downsample, encodeWavBytes } from './wav';
import { isDismissal, isLikelyHallucination, isStopCommand, isWakeToken, parseWakeCommand } from './wake-word';
import { splitForSpeech } from './reply-speaker';

const RATE = 16000;
const FRAME = 512; // 32 ms

function tone(amplitude: number): Float32Array {
  const f = new Float32Array(FRAME);
  for (let i = 0; i < FRAME; i++) f[i] = amplitude * Math.sin((2 * Math.PI * 220 * i) / RATE);
  return f;
}
function noise(amplitude: number, seed = 1): Float32Array {
  const f = new Float32Array(FRAME);
  let x = seed;
  for (let i = 0; i < FRAME; i++) {
    x = (x * 1103515245 + 12345) % 2147483648;
    f[i] = amplitude * ((x / 2147483648) * 2 - 1);
  }
  return f;
}

/** Feed frames for `ms` milliseconds; returns any utterances emitted. */
function feed(d: UtteranceDetector, make: (i: number) => Float32Array, ms: number): Float32Array[] {
  const out: Float32Array[] = [];
  const n = Math.round(ms / ((FRAME / RATE) * 1000));
  for (let i = 0; i < n; i++) {
    const u = d.push(make(i));
    if (u) out.push(u);
  }
  return out;
}

describe('UtteranceDetector', () => {
  it('cuts one utterance out of quiet-speech-quiet, with pre-roll', () => {
    const d = new UtteranceDetector({ sampleRate: RATE });
    expect(feed(d, (i) => noise(0.002, i + 1), 1000)).toHaveLength(0);
    expect(feed(d, () => tone(0.2), 1200)).toHaveLength(0);
    expect(d.inSpeech).toBe(true);
    const done = feed(d, (i) => noise(0.002, i + 7), 1200);
    expect(done).toHaveLength(1);
    const seconds = done[0].length / RATE;
    // 1.2 s of speech + ~0.4 s pre-roll + ~0.8 s trailing silence.
    expect(seconds).toBeGreaterThan(2.0);
    expect(seconds).toBeLessThan(2.8);
    expect(d.inSpeech).toBe(false);
  });

  it('ignores a short click', () => {
    const d = new UtteranceDetector({ sampleRate: RATE });
    feed(d, (i) => noise(0.002, i + 1), 500);
    expect(feed(d, () => tone(0.3), 64)).toHaveLength(0);
    expect(feed(d, (i) => noise(0.002, i + 3), 2000)).toHaveLength(0);
    expect(d.inSpeech).toBe(false);
  });

  it('adapts to a loud background so steady noise is not speech', () => {
    const d = new UtteranceDetector({ sampleRate: RATE });
    // A fan at a steady level well above the absolute floor.
    expect(feed(d, (i) => noise(0.03, i + 1), 4000)).toHaveLength(0);
  });

  it('caps very long utterances', () => {
    const d = new UtteranceDetector({ sampleRate: RATE, maxUtteranceMs: 3000 });
    feed(d, (i) => noise(0.002, i + 1), 300);
    const out = feed(d, () => tone(0.2), 4000);
    expect(out.length).toBeGreaterThanOrEqual(1);
    expect(out[0].length / RATE).toBeLessThanOrEqual(3.5);
  });

  it('requires louder speech while sensitivity is scaled up (assistant talking)', () => {
    const d = new UtteranceDetector({ sampleRate: RATE });
    feed(d, (i) => noise(0.002, i + 1), 500);
    d.setSensitivityScale(10);
    feed(d, () => tone(0.02), 1000);
    expect(d.inSpeech).toBe(false);
    feed(d, () => tone(0.4), 600);
    expect(d.inSpeech).toBe(true);
  });
});

describe('wav encoding', () => {
  it('downsamples 48 kHz to 16 kHz by a factor of three', () => {
    expect(downsample(new Float32Array(4800), 48000, 16000)).toHaveLength(1600);
  });

  it('writes a valid PCM16 mono header', () => {
    const bytes = encodeWavBytes(new Float32Array([0, 1, -1]), 16000);
    const view = new DataView(bytes.buffer);
    const tag = (o: number) => String.fromCharCode(...bytes.slice(o, o + 4));
    expect(tag(0)).toBe('RIFF');
    expect(tag(8)).toBe('WAVE');
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint32(40, true)).toBe(6);
    expect(view.getInt16(46, true)).toBe(32767);
    expect(view.getInt16(48, true)).toBe(-32768);
  });
});

describe('wake word', () => {
  it.each([
    ['Jarvis, what time is it?', 'What time is it?'],
    ['Hey Jarvis, turn on the lights.', 'Turn on the lights.'],
    ['Okay, Jarvis. Remind me to call mom.', 'Remind me to call mom.'],
    ['jervis what is the weather', 'What is the weather'],
    ["What's the weather like today, Jarvis?", "What's the weather like today?"],
    ['Jarvis.', ''],
    ['Hey, Jarvis!', ''],
  ])('%s -> %s', (said, command) => {
    expect(parseWakeCommand(said)).toEqual({ woke: true, command });
  });

  it.each([
    'What time is it?',
    'I told Travis about the meeting.',
    'The service was great, said Jarvis yesterday at the office.',
    'Thank you.',
  ])('ignores "%s"', (said) => {
    expect(parseWakeCommand(said).woke).toBe(false);
  });

  it('tolerates one transcription slip but not a different name', () => {
    expect(isWakeToken('Jarvis,', 'jarvis')).toBe(true);
    expect(isWakeToken("Jarvis's", 'jarvis')).toBe(true);
    expect(isWakeToken('Javis', 'jarvis')).toBe(true);
    expect(isWakeToken('Travis', 'jarvis')).toBe(false);
    expect(isWakeToken('Harvey', 'jarvis')).toBe(false);
  });

  it('supports a custom wake word', () => {
    expect(parseWakeCommand('Friday, status report.', 'friday')).toEqual({ woke: true, command: 'Status report.' });
  });

  it('recognises dismissals, stops and hallucinations', () => {
    expect(isDismissal("That's all.")).toBe(true);
    expect(isDismissal('Thanks, that is all.')).toBe(true);
    expect(isDismissal("Thank you Jarvis, that's all for now.")).toBe(true);
    expect(isDismissal("Okay, thank you, I'm done.")).toBe(true);
    expect(isDismissal('Never mind.')).toBe(true);
    expect(isDismissal('Goodbye, Jervis.')).toBe(true);
    expect(isDismissal('Okay.')).toBe(false);
    expect(isDismissal('Thanks, and what about tomorrow?')).toBe(false);
    expect(isDismissal('Nothing is working on my laptop')).toBe(false);
    expect(isDismissal('Thanks, Jarvis')).toBe(true);
    expect(isDismissal('Thanks for the report, what is next?')).toBe(false);
    expect(isStopCommand('Stop.')).toBe(true);
    expect(isStopCommand('Stop the timer at five')).toBe(false);
    expect(isLikelyHallucination('you')).toBe(true);
    expect(isLikelyHallucination('Thanks for watching!')).toBe(true);
    expect(isLikelyHallucination('What is the time?')).toBe(false);
  });
});

describe('splitForSpeech', () => {
  it('merges short sentences and splits long replies at sentence ends', () => {
    expect(splitForSpeech('Yes. Of course. The meeting is at three in the afternoon.')).toEqual([
      'Yes. Of course. The meeting is at three in the afternoon.',
    ]);
    const long = Array.from({ length: 6 }, (_, i) => `This is sentence number ${i + 1} of the reply.`).join(' ');
    const chunks = splitForSpeech(long);
    expect(chunks.length).toBe(6);
    expect(chunks.join(' ')).toBe(long);
  });

  it('splits a long opening sentence at a comma so speech starts sooner', () => {
    const first =
      'The historic Apollo 11 mission launched from Florida in July 1969, carrying Neil Armstrong, ' +
      'Buzz Aldrin and Michael Collins on a journey that would change history forever.';
    const chunks = splitForSpeech(`${first} It landed four days later.`);
    expect(chunks[0]).toBe('The historic Apollo 11 mission launched from Florida in July 1969, carrying Neil Armstrong,');
    expect(chunks.join(' ')).toBe(`${first} It landed four days later.`);
  });
});

describe('voice language', () => {
  it('defaults to the system language', async () => {
    const { resolveVoiceLanguage } = await import('./language');
    expect(resolveVoiceLanguage('', 'en-US')).toBe('en');
    expect(resolveVoiceLanguage('', 'sv-SE')).toBe('sv');
  });

  it('honours an explicit language or auto-detect', async () => {
    const { resolveVoiceLanguage } = await import('./language');
    expect(resolveVoiceLanguage('fa', 'en-US')).toBe('fa');
    expect(resolveVoiceLanguage('auto', 'en-US')).toBeUndefined();
    expect(resolveVoiceLanguage('', '')).toBeUndefined();
  });
});
