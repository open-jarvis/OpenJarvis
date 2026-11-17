import { describe, expect, it } from 'vitest';

import { createVoiceDetector, encodeWav, frameRms, resampleLinear } from './audio';

const FRAME_MS = 20;

/** Alimenta el detector con `ms` milisegundos de un mismo nivel y junta los eventos. */
function feed(detector: ReturnType<typeof createVoiceDetector>, level: number, ms: number) {
  const events: string[] = [];
  for (let elapsed = 0; elapsed < ms; elapsed += FRAME_MS) {
    const event = detector.process(level, FRAME_MS);
    if (event) events.push(event);
  }
  return events;
}

describe('frameRms', () => {
  it('calcula la raíz cuadrática media de un bloque', () => {
    expect(frameRms(new Float32Array([0.5, -0.5, 0.5, -0.5]))).toBeCloseTo(0.5);
    expect(frameRms(new Float32Array(0))).toBe(0);
  });
});

describe('createVoiceDetector', () => {
  it('ignora ruidos más cortos que la duración mínima de voz', () => {
    const detector = createVoiceDetector();
    feed(detector, 0.002, 500);
    expect(feed(detector, 0.2, 60)).toEqual([]);
    expect(feed(detector, 0.002, 500)).toEqual([]);
    expect(detector.isSpeaking()).toBe(false);
  });

  it('emite inicio y fin de voz con la pausa de cierre', () => {
    const detector = createVoiceDetector({ minSpeechMs: 120, hangoverMs: 600 });
    feed(detector, 0.002, 500);
    expect(feed(detector, 0.2, 400)).toEqual(['speech_start']);
    expect(detector.isSpeaking()).toBe(true);
    // Una pausa breve entre palabras no cierra la frase
    expect(feed(detector, 0.002, 300)).toEqual([]);
    expect(feed(detector, 0.2, 200)).toEqual([]);
    expect(feed(detector, 0.002, 700)).toEqual(['speech_end']);
    expect(detector.isSpeaking()).toBe(false);
  });

  it('corta una frase que supera la duración máxima', () => {
    const detector = createVoiceDetector({ maxSpeechMs: 1000 });
    feed(detector, 0.002, 300);
    expect(feed(detector, 0.2, 1100)).toEqual(['speech_start', 'speech_end']);
  });

  it('se adapta al ruido de fondo para no dispararse con un ambiente ruidoso', () => {
    const detector = createVoiceDetector();
    // Ambiente constante por encima del umbral base: tras adaptarse no cuenta como voz
    feed(detector, 0.03, 4000);
    detector.reset();
    feed(detector, 0.03, 4000);
    expect(detector.isSpeaking()).toBe(false);
    expect(feed(detector, 0.3, 400)).toEqual(['speech_start']);
  });

  it('sube la exigencia cuando se le pide (mientras Jarvis habla)', () => {
    const detector = createVoiceDetector();
    feed(detector, 0.002, 500);
    detector.setSensitivityFactor(4);
    expect(feed(detector, 0.04, 400)).toEqual([]);
    detector.setSensitivityFactor(1);
    expect(feed(detector, 0.04, 400)).toEqual(['speech_start']);
  });
});

describe('resampleLinear', () => {
  it('reduce la frecuencia de muestreo conservando la duración', () => {
    const input = new Float32Array(48000).fill(0.25);
    const output = resampleLinear(input, 48000, 16000);
    expect(output.length).toBe(16000);
    expect(output[100]).toBeCloseTo(0.25);
  });

  it('devuelve la misma señal cuando la frecuencia no cambia', () => {
    const input = new Float32Array([0.1, 0.2, 0.3]);
    expect(resampleLinear(input, 16000, 16000)).toBe(input);
  });
});

describe('encodeWav', () => {
  it('escribe una cabecera RIFF/WAVE mono de 16 bits válida', () => {
    const samples = new Float32Array([0, 1, -1, 0.5]);
    const view = new DataView(encodeWav(samples, 16000));
    const tag = (offset: number) =>
      String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(offset + i)));

    expect(tag(0)).toBe('RIFF');
    expect(tag(8)).toBe('WAVE');
    expect(tag(12)).toBe('fmt ');
    expect(tag(36)).toBe('data');
    expect(view.getUint16(22, true)).toBe(1); // canales
    expect(view.getUint32(24, true)).toBe(16000); // frecuencia
    expect(view.getUint16(34, true)).toBe(16); // bits por muestra
    expect(view.getUint32(40, true)).toBe(samples.length * 2);
    expect(view.byteLength).toBe(44 + samples.length * 2);
  });

  it('convierte las muestras a PCM con saturación en los extremos', () => {
    const view = new DataView(encodeWav(new Float32Array([0, 1, -1, 2]), 16000));
    expect(view.getInt16(44, true)).toBe(0);
    expect(view.getInt16(46, true)).toBe(32767);
    expect(view.getInt16(48, true)).toBe(-32768);
    expect(view.getInt16(50, true)).toBe(32767);
  });
});
