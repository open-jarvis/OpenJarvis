/**
 * Encode captured microphone samples as a 16-bit mono WAV file.
 *
 * Hands-free mode captures raw PCM (rather than using MediaRecorder) so it can
 * keep a short pre-roll from before speech was detected. Whisper works at
 * 16 kHz, so the audio is downsampled before upload, which also keeps each
 * request small.
 */

export const STT_SAMPLE_RATE = 16000;

/** Downsample by averaging the source samples that fall into each output sample. */
export function downsample(samples: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (targetRate >= sourceRate) return samples;
  const ratio = sourceRate / targetRate;
  const outLength = Math.floor(samples.length / ratio);
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

/** Build the bytes of a PCM16 mono WAV file. */
export function encodeWavBytes(samples: Float32Array, sampleRate: number): Uint8Array<ArrayBuffer> {
  const dataBytes = samples.length * 2;
  const buf = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buf);
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeStr(36, 'data');
  view.setUint32(40, dataBytes, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

/** Downsample to 16 kHz and wrap as an `audio/wav` blob ready for transcription. */
export function encodeUtteranceWav(samples: Float32Array, sourceRate: number): Blob {
  const pcm = downsample(samples, sourceRate, STT_SAMPLE_RATE);
  return new Blob([encodeWavBytes(pcm, STT_SAMPLE_RATE)], { type: 'audio/wav' });
}
