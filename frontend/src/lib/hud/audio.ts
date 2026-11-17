/**
 * Matemática de audio del HUD, sin dependencias del navegador para poder
 * probarla: nivel de un bloque, detector de voz y codificación WAV.
 */

/** Nivel (raíz cuadrática media) de un bloque de muestras en el rango 0..1. */
export function frameRms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sumOfSquares = 0;
  for (let i = 0; i < samples.length; i += 1) sumOfSquares += samples[i] * samples[i];
  return Math.sqrt(sumOfSquares / samples.length);
}

export type VoiceEvent = 'speech_start' | 'speech_end';

export interface VoiceDetectorOptions {
  /** Nivel mínimo para considerar voz en un ambiente silencioso. */
  baseThreshold?: number;
  /** Cuántas veces por encima del ruido de fondo debe estar la voz. */
  noiseMultiplier?: number;
  /** Voz continua necesaria para abrir una frase (descarta golpes y clics). */
  minSpeechMs?: number;
  /** Silencio que cierra la frase (las pausas entre palabras son más cortas). */
  hangoverMs?: number;
  /** Duración máxima de una frase antes de cortarla. */
  maxSpeechMs?: number;
  /** Ventana sobre la que se estima el ruido de fondo. */
  noiseWindowMs?: number;
}

export interface VoiceDetector {
  /** Procesa el nivel de un bloque de `frameMs` milisegundos. */
  process(level: number, frameMs: number): VoiceEvent | null;
  isSpeaking(): boolean;
  /** Abandona la frase en curso conservando el ruido de fondo aprendido. */
  reset(): void;
  /** Factor > 1 exige más volumen; se usa mientras suena la voz de Jarvis. */
  setSensitivityFactor(factor: number): void;
}

/** Histéresis: una vez abierta la frase, se mantiene con un nivel algo menor. */
const END_THRESHOLD_RATIO = 0.6;

/**
 * Detector de voz por energía con ruido de fondo adaptativo.
 *
 * El ruido se estima como el mínimo del nivel en una ventana deslizante: la
 * voz tiene valles entre sílabas y palabras, así que el mínimo sigue al
 * ambiente; un nivel constante (ventilador, música) termina tratado como ruido.
 */
export function createVoiceDetector(options: VoiceDetectorOptions = {}): VoiceDetector {
  const baseThreshold = options.baseThreshold ?? 0.015;
  const noiseMultiplier = options.noiseMultiplier ?? 2.5;
  const minSpeechMs = options.minSpeechMs ?? 120;
  const hangoverMs = options.hangoverMs ?? 800;
  const maxSpeechMs = options.maxSpeechMs ?? 15000;
  const noiseWindowMs = options.noiseWindowMs ?? 3000;

  const window: Array<{ level: number; ms: number }> = [];
  let windowMs = 0;
  let speaking = false;
  let voicedRunMs = 0;
  let silenceMs = 0;
  let speechMs = 0;
  let sensitivityFactor = 1;

  const trackNoise = (level: number, frameMs: number): number => {
    window.push({ level, ms: frameMs });
    windowMs += frameMs;
    while (windowMs > noiseWindowMs && window.length > 1) {
      windowMs -= window.shift()!.ms;
    }
    let floor = Infinity;
    for (const frame of window) floor = Math.min(floor, frame.level);
    return floor;
  };

  const endSpeech = (): VoiceEvent => {
    speaking = false;
    voicedRunMs = 0;
    silenceMs = 0;
    speechMs = 0;
    return 'speech_end';
  };

  return {
    process(level, frameMs) {
      const noiseFloor = trackNoise(level, frameMs);
      const startThreshold =
        Math.max(baseThreshold, noiseFloor * noiseMultiplier) * sensitivityFactor;

      if (!speaking) {
        voicedRunMs = level >= startThreshold ? voicedRunMs + frameMs : 0;
        if (voicedRunMs < minSpeechMs) return null;
        speaking = true;
        speechMs = voicedRunMs;
        silenceMs = 0;
        return 'speech_start';
      }

      speechMs += frameMs;
      silenceMs = level >= startThreshold * END_THRESHOLD_RATIO ? 0 : silenceMs + frameMs;
      return silenceMs >= hangoverMs || speechMs >= maxSpeechMs ? endSpeech() : null;
    },
    isSpeaking: () => speaking,
    reset() {
      endSpeech();
    },
    setSensitivityFactor(factor) {
      sensitivityFactor = Math.max(1, factor);
    },
  };
}

/** Cambia la frecuencia de muestreo por interpolación lineal. */
export function resampleLinear(
  samples: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const output = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < output.length; i += 1) {
    const position = i * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, samples.length - 1);
    const weight = position - left;
    output[i] = samples[left] * (1 - weight) + samples[right] * weight;
  }
  return output;
}

const WAV_HEADER_BYTES = 44;
const BYTES_PER_SAMPLE = 2;

/** Codifica audio mono como WAV PCM de 16 bits, el formato que lee Whisper sin conversión. */
export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const dataBytes = samples.length * BYTES_PER_SAMPLE;
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);
  const writeTag = (offset: number, tag: string) => {
    for (let i = 0; i < tag.length; i += 1) view.setUint8(offset + i, tag.charCodeAt(i));
  };

  writeTag(0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true);
  writeTag(8, 'WAVE');
  writeTag(12, 'fmt ');
  view.setUint32(16, 16, true); // tamaño del bloque fmt
  view.setUint16(20, 1, true); // formato PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true); // bytes por segundo
  view.setUint16(32, BYTES_PER_SAMPLE, true); // bytes por muestra
  view.setUint16(34, 16, true); // bits por muestra
  writeTag(36, 'data');
  view.setUint32(40, dataBytes, true);

  for (let i = 0; i < samples.length; i += 1) {
    // Saturación: una muestra fuera de [-1, 1] no debe desbordar el entero.
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    const pcm = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    view.setInt16(WAV_HEADER_BYTES + i * BYTES_PER_SAMPLE, Math.round(pcm), true);
  }
  return buffer;
}
