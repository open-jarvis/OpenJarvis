/**
 * Voz de Jarvis con el sintetizador del propio navegador (Web Speech API).
 *
 * No consume memoria del servidor ni cuesta nada, y empieza a hablar al
 * instante. En Edge las voces "Online (Natural)" son neuronales.
 */
import type { SpeechQueueCallbacks, VoiceOutput } from './speech-queue';
import { pickSpanishVoice } from './browser-voice';

/**
 * Edge carga sus voces neuronales desde internet y pueden tardar unos segundos
 * en aparecer; mientras tanto solo ofrece las locales (a veces ninguna en español).
 */
const SPANISH_VOICE_TIMEOUT_MS = 6000;
const VOICE_POLL_MS = 250;
/** El navegador no expone el audio: la animación usa un nivel simulado. */
const BASE_LEVEL = 0.06;
const WORD_PULSE = 0.07;
const PULSE_DECAY_MS = 180;

/** Espera a que el navegador ofrezca una voz en español, o se rinde al vencer el plazo. */
async function waitForSpanishVoice(synth: SpeechSynthesis): Promise<SpeechSynthesisVoice | null> {
  const deadline = Date.now() + SPANISH_VOICE_TIMEOUT_MS;
  // getVoices() se consulta en bucle: el evento "voiceschanged" no llega en todos los navegadores.
  for (;;) {
    const voice = pickSpanishVoice(synth.getVoices());
    if (voice || Date.now() >= deadline) return voice;
    await new Promise((resolve) => setTimeout(resolve, VOICE_POLL_MS));
  }
}

export class BrowserSpeechQueue implements VoiceOutput {
  /**
   * Las locuciones pendientes se guardan aquí: si nadie las referencia,
   * algunos navegadores las descartan antes de terminar y nunca avisan del fin.
   */
  private pending: SpeechSynthesisUtterance[] = [];
  private speaking = false;
  private lastPulseAt = 0;

  private constructor(
    private readonly synth: SpeechSynthesis,
    readonly voice: SpeechSynthesisVoice,
    private readonly callbacks: SpeechQueueCallbacks,
  ) {}

  /** Crea la cola si el navegador tiene una voz en español; si no, devuelve null. */
  static async create(callbacks: SpeechQueueCallbacks = {}): Promise<BrowserSpeechQueue | null> {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;
    const synth = window.speechSynthesis;
    const voice = await waitForSpanishVoice(synth);
    return voice ? new BrowserSpeechQueue(synth, voice, callbacks) : null;
  }

  enqueue(text: string): void {
    if (!text.trim()) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = this.voice;
    utterance.lang = this.voice.lang;

    utterance.onstart = () => {
      this.callbacks.onSentenceStart?.(text);
      this.setSpeaking(true);
    };
    utterance.onboundary = () => {
      this.lastPulseAt = performance.now();
    };
    const finish = () => {
      this.pending = this.pending.filter((item) => item !== utterance);
      if (this.pending.length === 0) this.setSpeaking(false);
    };
    utterance.onend = finish;
    utterance.onerror = (event) => {
      // "interrupted"/"canceled" son el resultado normal de stop().
      if (event.error !== 'interrupted' && event.error !== 'canceled') {
        this.callbacks.onError?.(event.error);
      }
      finish();
    };

    this.pending.push(utterance);
    this.synth.speak(utterance);
  }

  stop(): void {
    // Se sueltan los manejadores antes de cancelar para que no disparen tarde.
    for (const utterance of this.pending) {
      utterance.onstart = null;
      utterance.onend = null;
      utterance.onerror = null;
      utterance.onboundary = null;
    }
    this.pending = [];
    this.synth.cancel();
    this.setSpeaking(false);
  }

  getLevel(): number {
    if (!this.speaking) return 0;
    const sincePulse = performance.now() - this.lastPulseAt;
    const pulse = sincePulse < PULSE_DECAY_MS ? WORD_PULSE * (1 - sincePulse / PULSE_DECAY_MS) : 0;
    // Una ondulación leve mantiene vivo el núcleo entre palabras.
    const wave = 0.02 * Math.abs(Math.sin(performance.now() / 90));
    return BASE_LEVEL + wave + pulse;
  }

  private setSpeaking(speaking: boolean): void {
    if (this.speaking === speaking) return;
    this.speaking = speaking;
    this.callbacks.onSpeakingChange?.(speaking);
  }
}
