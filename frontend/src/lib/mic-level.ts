/**
 * Tracks the peak input level of a microphone stream while it records.
 *
 * Some capture failures (a stuck USB mic, a device muted at the driver level)
 * still hand the webview a "live" track, but every sample is exactly zero. The
 * MediaRecorder then writes only a container header, and the server fails with
 * an opaque "End of file" error. Measuring the level lets the UI report the
 * real problem instead.
 */

/** Minimum number of level samples before a recording can be judged silent. */
export const MIN_SAMPLES_FOR_VERDICT = 3;

export const NO_AUDIO_MESSAGE =
  'No audio reached the app from your microphone. Check that it is not muted, ' +
  'then unplug and reconnect it or pick another input device in Windows sound settings.';

export interface LevelMeter {
  /** Highest absolute sample value seen so far, in [0, 1]. */
  peak(): number;
  /** Number of times the level was sampled. */
  samples(): number;
  stop(): void;
}

/** Peak absolute value of a block of float samples. */
export function blockPeak(block: ArrayLike<number>): number {
  let peak = 0;
  for (let i = 0; i < block.length; i++) {
    const v = Math.abs(block[i]);
    if (v > peak) peak = v;
  }
  return peak;
}

/**
 * True when the meter saw enough of the recording to be sure that the
 * microphone delivered only digital silence. A working mic always has a noise
 * floor, so an exact zero peak means no audio arrived at all.
 */
export function isDigitalSilence(meter: Pick<LevelMeter, 'peak' | 'samples'> | null): boolean {
  if (!meter) return false;
  return meter.samples() >= MIN_SAMPLES_FOR_VERDICT && meter.peak() === 0;
}

/**
 * Start measuring ``stream``. Returns null when Web Audio is unavailable, in
 * which case callers skip the silence check rather than fail the recording.
 */
export function startLevelMeter(stream: MediaStream, intervalMs = 100): LevelMeter | null {
  const Ctx: typeof AudioContext | undefined =
    typeof window !== 'undefined'
      ? window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      : undefined;
  if (!Ctx) return null;

  let ctx: AudioContext;
  try {
    ctx = new Ctx();
    const analyser = ctx.createAnalyser();
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    let peak = 0;
    let samples = 0;
    const timer = setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      peak = Math.max(peak, blockPeak(buf));
      samples += 1;
    }, intervalMs);
    return {
      peak: () => peak,
      samples: () => samples,
      stop: () => {
        clearInterval(timer);
        ctx.close().catch(() => {});
      },
    };
  } catch {
    return null;
  }
}
