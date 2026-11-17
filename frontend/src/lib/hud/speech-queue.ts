/**
 * Cola de voz del HUD: sintetiza y reproduce frases en orden, una tras otra.
 *
 * A diferencia de `useTtsStore` (una sola locución por respuesta completa),
 * aquí la voz arranca con la primera frase mientras las siguientes se
 * sintetizan, y el audio pasa por un analizador para animar el núcleo.
 */
import { synthesizeSpeech } from '../api';
import { frameRms } from './audio';

export interface SpeechQueueCallbacks {
  /** Se llama justo cuando empieza a sonar cada frase (subtítulos sincronizados). */
  onSentenceStart?: (text: string) => void;
  onSpeakingChange?: (speaking: boolean) => void;
  onError?: (message: string) => void;
}

interface QueueItem {
  text: string;
  audio: Promise<AudioBuffer | null> | null;
}

/** Frases que se sintetizan por adelantado mientras suena la actual. */
const PREFETCH_DEPTH = 2;
/** Muestras que se leen para medir el nivel de la voz. */
const ANALYSER_SIZE = 1024;

export class SpeechQueue {
  private readonly analyser: AnalyserNode;
  private readonly levelBuffer = new Float32Array(ANALYSER_SIZE);
  private items: QueueItem[] = [];
  private currentSource: AudioBufferSourceNode | null = null;
  private abortController = new AbortController();
  /** Cambia en cada `stop()`: el trabajo de una generación anterior se descarta. */
  private generation = 0;
  private draining = false;

  constructor(
    private readonly audioContext: AudioContext,
    private readonly callbacks: SpeechQueueCallbacks = {},
  ) {
    this.analyser = audioContext.createAnalyser();
    this.analyser.fftSize = ANALYSER_SIZE;
    this.analyser.connect(audioContext.destination);
  }

  enqueue(text: string): void {
    if (!text.trim()) return;
    this.items.push({ text, audio: null });
    this.prefetch();
    void this.drain();
  }

  /** Silencia de inmediato y descarta lo pendiente. */
  stop(): void {
    this.generation += 1;
    this.abortController.abort();
    this.abortController = new AbortController();
    this.items = [];
    if (this.currentSource) {
      this.currentSource.onended = null;
      try {
        this.currentSource.stop();
      } catch {
        // La fuente ya había terminado.
      }
      this.currentSource = null;
    }
    if (this.draining) {
      this.draining = false;
      this.callbacks.onSpeakingChange?.(false);
    }
  }

  /** Nivel actual de la voz (0..1) para la animación. */
  getLevel(): number {
    if (!this.currentSource) return 0;
    this.analyser.getFloatTimeDomainData(this.levelBuffer);
    return frameRms(this.levelBuffer);
  }

  private prefetch(): void {
    for (const item of this.items.slice(0, PREFETCH_DEPTH)) {
      if (!item.audio) item.audio = this.synthesize(item.text);
    }
  }

  private async synthesize(text: string): Promise<AudioBuffer | null> {
    const generation = this.generation;
    try {
      const blob = await synthesizeSpeech(text, { signal: this.abortController.signal });
      return await this.audioContext.decodeAudioData(await blob.arrayBuffer());
    } catch (error) {
      // Una frase que falla se omite; el resto de la respuesta sigue sonando.
      if (generation === this.generation) {
        this.callbacks.onError?.(error instanceof Error ? error.message : 'Fallo de síntesis');
      }
      return null;
    }
  }

  private async drain(): Promise<void> {
    if (this.draining) return;
    this.draining = true;
    const generation = this.generation;
    this.callbacks.onSpeakingChange?.(true);

    while (this.items.length > 0) {
      const item = this.items[0];
      const buffer = await item.audio;
      if (generation !== this.generation) return;
      if (buffer) {
        this.callbacks.onSentenceStart?.(item.text);
        await this.play(buffer);
        if (generation !== this.generation) return;
      }
      this.items.shift();
      this.prefetch();
    }

    this.draining = false;
    this.callbacks.onSpeakingChange?.(false);
  }

  private play(buffer: AudioBuffer): Promise<void> {
    return new Promise((resolve) => {
      const source = this.audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(this.analyser);
      source.onended = () => {
        if (this.currentSource === source) this.currentSource = null;
        resolve();
      };
      this.currentSource = source;
      source.start();
    });
  }
}
