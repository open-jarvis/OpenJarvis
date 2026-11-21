import { toSpeakableText } from '../message-text';

/**
 * Speaks assistant replies for hands-free mode.
 *
 * A reply is split into sentence-sized chunks. The next chunk is synthesized
 * while the current one plays, so speech starts after the first sentence is
 * ready instead of after the whole reply. If the server has no TTS backend,
 * the platform's built-in `speechSynthesis` voices are used instead.
 */

const SENTENCE_BREAK = /(?<=[.!?…])\s+/;
const MIN_CHUNK_CHARS = 24;
const MAX_CHUNK_CHARS = 260;
/** The first chunk decides how soon speech starts, so keep it short. */
const FIRST_CHUNK_TARGET = 110;

/** Split speakable text into chunks of whole sentences. */
export function splitForSpeech(text: string): string[] {
  const chunks: string[] = [];
  let pending = '';
  for (const sentence of text.trim().split(SENTENCE_BREAK)) {
    if (!sentence) continue;
    const candidate = pending ? `${pending} ${sentence}` : sentence;
    if (candidate.length > MAX_CHUNK_CHARS && pending) {
      chunks.push(pending);
      pending = sentence;
    } else {
      pending = candidate;
    }
    if (pending.length >= MIN_CHUNK_CHARS) {
      chunks.push(pending);
      pending = '';
    }
  }
  if (pending) chunks.push(pending);
  return splitFirstAtClause(chunks);
}

/** Break a long opening sentence at a comma so the first audio is ready sooner. */
function splitFirstAtClause(chunks: string[]): string[] {
  const first = chunks[0];
  if (!first || first.length <= FIRST_CHUNK_TARGET * 1.3) return chunks;
  const window = first.slice(0, FIRST_CHUNK_TARGET + 20);
  const cut = Math.max(window.lastIndexOf(', '), window.lastIndexOf('; '));
  if (cut < 30) return chunks;
  return [first.slice(0, cut + 1), first.slice(cut + 2), ...chunks.slice(1)];
}

export type Synthesize = (text: string, signal: AbortSignal) => Promise<Blob>;

export interface ReplySpeakerOptions {
  synthesize: Synthesize;
  /** Called with each chunk as it starts playing. */
  onChunk?: (text: string) => void;
}

export class ReplySpeaker {
  private controller: AbortController | null = null;
  private audio: HTMLAudioElement | null = null;
  private finishCurrent: (() => void) | null = null;
  /** Set once server synthesis fails, so later replies go straight to the fallback. */
  private serverUnavailable = false;

  constructor(private readonly opts: ReplySpeakerOptions) {}

  get speaking(): boolean {
    return this.controller !== null;
  }

  /** Speak `text`; resolves when it has finished playing or was cancelled. */
  async speak(text: string): Promise<void> {
    this.cancel();
    const speakable = toSpeakableText(text);
    if (!speakable) return;
    const chunks = splitForSpeech(speakable);
    const controller = new AbortController();
    this.controller = controller;
    try {
      if (!this.serverUnavailable) {
        try {
          await this.speakWithServer(chunks, controller.signal);
          return;
        } catch (err) {
          if (controller.signal.aborted) return;
          // Only fall back when nothing has been spoken yet; otherwise the
          // reply would restart from the top in a different voice.
          if (!(err instanceof FirstChunkError)) throw err;
          this.serverUnavailable = true;
        }
      }
      await this.speakWithBrowser(speakable, controller.signal);
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  cancel(): void {
    // Silence the element before aborting: abort listeners run synchronously
    // and clear `this.audio`, which would leave the clip playing to the end.
    const el = this.audio;
    if (el) {
      el.onended = null;
      el.onerror = null;
      el.pause();
    }
    this.audio = null;
    this.controller?.abort();
    this.controller = null;
    this.finishCurrent?.();
    this.finishCurrent = null;
    if (typeof window !== 'undefined' && window.speechSynthesis?.speaking) {
      window.speechSynthesis.cancel();
    }
  }

  /** Let a later reply try the server again (e.g. after Kokoro was installed). */
  resetServerAvailability(): void {
    this.serverUnavailable = false;
  }

  private async speakWithServer(chunks: string[], signal: AbortSignal): Promise<void> {
    let next: Promise<Blob> | null = this.opts.synthesize(chunks[0], signal);
    for (let i = 0; i < chunks.length; i++) {
      let blob: Blob;
      try {
        blob = await next!;
      } catch (err) {
        if (i === 0) throw new FirstChunkError(err);
        throw err;
      }
      if (signal.aborted) return;
      // Prefetch the following chunk while this one plays.
      next = i + 1 < chunks.length ? this.opts.synthesize(chunks[i + 1], signal) : null;
      next?.catch(() => {}); // surfaced when awaited
      this.opts.onChunk?.(chunks[i]);
      await this.play(blob, signal);
      if (signal.aborted) return;
    }
  }

  private play(blob: Blob, signal: AbortSignal): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const el = new Audio(url);
      this.audio = el;
      const done = (err?: unknown) => {
        URL.revokeObjectURL(url);
        if (this.audio === el) this.audio = null;
        this.finishCurrent = null;
        signal.removeEventListener('abort', onAbort);
        if (err) reject(err);
        else resolve();
      };
      const onAbort = () => {
        el.pause();
        done();
      };
      this.finishCurrent = () => done();
      signal.addEventListener('abort', onAbort);
      el.onended = () => done();
      el.onerror = () => done(new Error('Playback failed'));
      el.play().catch((err) => done(err));
    });
  }

  private speakWithBrowser(text: string, signal: AbortSignal): Promise<void> {
    const synth = typeof window !== 'undefined' ? window.speechSynthesis : undefined;
    if (!synth) return Promise.reject(new Error('No text-to-speech voice is available'));
    return new Promise<void>((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      const voices = synth.getVoices();
      const preferred =
        voices.find((v) => v.lang === 'en-GB' && /male|george|ryan|thomas/i.test(v.name)) ??
        voices.find((v) => v.lang === 'en-GB') ??
        voices.find((v) => v.lang.startsWith('en'));
      if (preferred) utterance.voice = preferred;
      const finish = () => {
        signal.removeEventListener('abort', finish);
        this.finishCurrent = null;
        resolve();
      };
      this.finishCurrent = finish;
      signal.addEventListener('abort', () => {
        synth.cancel();
        finish();
      });
      utterance.onend = finish;
      utterance.onerror = finish;
      this.opts.onChunk?.(text);
      synth.speak(utterance);
    });
  }
}

class FirstChunkError extends Error {
  constructor(readonly cause: unknown) {
    super(cause instanceof Error ? cause.message : String(cause));
  }
}
