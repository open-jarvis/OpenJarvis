/**
 * Energy-based voice activity detector that cuts a continuous microphone
 * stream into utterances.
 *
 * Feed it fixed-size frames of float PCM. It tracks the background noise
 * floor, starts an utterance once the level stays above that floor for
 * `minSpeechMs`, and ends it after `endSilenceMs` of quiet. Each utterance
 * includes `preRollMs` of audio from before the detector triggered, so the
 * first syllable ("Jar-") is not clipped.
 */

export interface DetectorOptions {
  sampleRate: number;
  /** Absolute RMS floor for speech, used in very quiet rooms. */
  minThreshold?: number;
  /** Speech must be this many times louder than the background noise floor. */
  floorMultiplier?: number;
  /** Loud audio shorter than this (a click, a cough) is ignored. */
  minSpeechMs?: number;
  /** Quiet gap that ends an utterance. */
  endSilenceMs?: number;
  /** Audio kept from before speech started. */
  preRollMs?: number;
  /** Hard cap on one utterance. */
  maxUtteranceMs?: number;
}

export function rms(frame: ArrayLike<number>): number {
  if (frame.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / frame.length);
}

type Phase = 'idle' | 'pending' | 'speech';

export class UtteranceDetector {
  private readonly opts: Required<DetectorOptions>;
  private phase: Phase = 'idle';
  private noiseFloor = -1;
  private preRoll: Float32Array[] = [];
  private preRollSamples = 0;
  private frames: Float32Array[] = [];
  private voicedMs = 0;
  private quietMs = 0;
  private totalMs = 0;
  /** Multiplier applied on top of the normal threshold (raised while Jarvis talks). */
  private sensitivityScale = 1;
  /** RMS of the most recent frame, for level meters. */
  lastLevel = 0;

  constructor(opts: DetectorOptions) {
    this.opts = {
      minThreshold: 0.01,
      floorMultiplier: 3,
      minSpeechMs: 250,
      endSilenceMs: 800,
      preRollMs: 400,
      maxUtteranceMs: 20000,
      ...opts,
    };
  }

  /** True while an utterance is being captured. */
  get inSpeech(): boolean {
    return this.phase === 'speech';
  }

  get threshold(): number {
    const floor = Math.max(this.noiseFloor, 0);
    return Math.max(this.opts.minThreshold, floor * this.opts.floorMultiplier) * this.sensitivityScale;
  }

  /**
   * Require louder speech (scale > 1), e.g. while the assistant's own voice is
   * playing, so only someone talking over it starts an utterance.
   */
  setSensitivityScale(scale: number): void {
    this.sensitivityScale = Math.max(1, scale);
  }

  /** Drop any partial utterance (the noise floor estimate is kept). */
  reset(): void {
    this.phase = 'idle';
    this.frames = [];
    this.voicedMs = 0;
    this.quietMs = 0;
    this.totalMs = 0;
  }

  /** Push one frame. Returns the finished utterance's samples, or null. */
  push(input: Float32Array): Float32Array | null {
    // The caller's buffer may be reused by the audio graph; keep our own copy.
    const frame = new Float32Array(input);
    const frameMs = (frame.length / this.opts.sampleRate) * 1000;
    const level = rms(frame);
    this.lastLevel = level;

    if (this.noiseFloor < 0) this.noiseFloor = level;
    const loud = level > this.threshold;

    switch (this.phase) {
      case 'idle': {
        // Only learn the floor from audio that is not speech, and not while the
        // threshold is raised: the assistant's own voice is not background
        // noise, and learning it would stack a second penalty on barge-in.
        if (!loud && this.sensitivityScale === 1) {
          this.noiseFloor = this.noiseFloor * 0.95 + level * 0.05;
        }
        this.remember(frame);
        if (loud) {
          this.phase = 'pending';
          this.frames = [frame];
          this.voicedMs = frameMs;
          this.quietMs = 0;
        }
        return null;
      }
      case 'pending': {
        this.frames.push(frame);
        if (loud) {
          this.voicedMs += frameMs;
          this.quietMs = 0;
        } else {
          this.quietMs += frameMs;
        }
        if (this.voicedMs >= this.opts.minSpeechMs) {
          // Confirmed speech: prepend the pre-roll captured before the trigger.
          this.frames = [...this.preRoll, ...this.frames];
          this.preRoll = [];
          this.preRollSamples = 0;
          this.totalMs = this.frames.reduce((ms, f) => ms + (f.length / this.opts.sampleRate) * 1000, 0);
          this.phase = 'speech';
        } else if (this.quietMs >= 200) {
          // Too short to be speech; fold it back into the pre-roll.
          for (const f of this.frames) this.remember(f);
          this.reset();
        }
        return null;
      }
      case 'speech': {
        this.frames.push(frame);
        this.totalMs += frameMs;
        // Hysteresis: once talking, a softer level still counts as speech.
        if (level > this.threshold * 0.6) this.quietMs = 0;
        else this.quietMs += frameMs;
        if (this.quietMs >= this.opts.endSilenceMs || this.totalMs >= this.opts.maxUtteranceMs) {
          const out = concat(this.frames);
          this.reset();
          return out;
        }
        return null;
      }
    }
  }

  private remember(frame: Float32Array): void {
    this.preRoll.push(frame);
    this.preRollSamples += frame.length;
    const maxSamples = (this.opts.preRollMs / 1000) * this.opts.sampleRate;
    while (this.preRoll.length > 1 && this.preRollSamples - this.preRoll[0].length >= maxSamples) {
      this.preRollSamples -= this.preRoll.shift()!.length;
    }
  }
}

function concat(frames: Float32Array[]): Float32Array {
  const total = frames.reduce((n, f) => n + f.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const f of frames) {
    out.set(f, offset);
    offset += f.length;
  }
  return out;
}
