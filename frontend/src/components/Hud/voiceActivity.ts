/**
 * Voice activity detection for hands-free listening.
 *
 * Fed the microphone level (0..1) many times a second, it decides when the
 * user starts talking and when they have paused long enough to send. It first
 * measures the room's background level, so a fan or traffic is not taken as
 * speech, and keeps adapting to it while waiting.
 */

export interface VoiceActivityOptions {
  /** How long to measure background noise before listening. */
  calibrationMs: number;
  /** Lowest level that can ever count as speech. */
  minStartLevel: number;
  /** Speech must be this many times louder than the background. */
  startFactor: number;
  /** Level must stay above the start threshold this long (ignores clicks). */
  speechStartMs: number;
  /** Quiet this long after speech ends the utterance. */
  silenceMs: number;
  /** Hard cap on one utterance. */
  maxUtteranceMs: number;
  /** No speech for this long reports a timeout (to restart the recording). */
  idleTimeoutMs: number;
}

export type VoiceActivityEvent = 'none' | 'speech-start' | 'speech-end' | 'timeout';

export const DEFAULT_VOICE_ACTIVITY: VoiceActivityOptions = {
  calibrationMs: 500,
  minStartLevel: 0.08,
  startFactor: 2.5,
  speechStartMs: 120,
  silenceMs: 1100,
  maxUtteranceMs: 30_000,
  idleTimeoutMs: 45_000,
};

/** Fraction of the start threshold below which audio counts as silence. */
const STOP_RATIO = 0.6;
/** How quickly the background estimate follows the room while waiting. */
const FLOOR_ADAPT = 0.02;

export function createVoiceActivity(options: Partial<VoiceActivityOptions> = {}) {
  const o: VoiceActivityOptions = { ...DEFAULT_VOICE_ACTIVITY, ...options };
  let phase: 'calibrating' | 'waiting' | 'speaking' | 'done' = 'calibrating';
  let startedAt: number | null = null;
  let calibrationSum = 0;
  let calibrationCount = 0;
  let floor = 0;
  let loudSince: number | null = null;
  let lastLoud = 0;
  let speechAt = 0;
  let waitingSince = 0;
  let heard = false;

  const startLevel = () => Math.max(o.minStartLevel, floor * o.startFactor);

  function update(level: number, now: number): VoiceActivityEvent {
    if (startedAt === null) startedAt = now;
    if (phase === 'done') return 'none';

    if (phase === 'calibrating') {
      calibrationSum += level;
      calibrationCount += 1;
      if (now - startedAt >= o.calibrationMs) {
        floor = calibrationSum / calibrationCount;
        phase = 'waiting';
        waitingSince = now;
      }
      return 'none';
    }

    if (phase === 'waiting') {
      const threshold = startLevel();
      if (level >= threshold) {
        loudSince ??= now;
        if (now - loudSince >= o.speechStartMs) {
          phase = 'speaking';
          heard = true;
          speechAt = loudSince;
          lastLoud = now;
          return 'speech-start';
        }
      } else {
        loudSince = null;
        floor += (level - floor) * FLOOR_ADAPT;
      }
      if (now - waitingSince >= o.idleTimeoutMs) {
        phase = 'done';
        return 'timeout';
      }
      return 'none';
    }

    // speaking
    if (level >= startLevel() * STOP_RATIO) lastLoud = now;
    if (now - lastLoud >= o.silenceMs || now - speechAt >= o.maxUtteranceMs) {
      phase = 'done';
      return 'speech-end';
    }
    return 'none';
  }

  return {
    update,
    /** True once any speech was detected (false means: nothing to transcribe). */
    heardSpeech: () => heard,
  };
}

export type VoiceActivity = ReturnType<typeof createVoiceActivity>;
