import { synthesizeSpeech, transcribeAudio } from './api';

export type SpeechProviderLocation = 'browser' | 'local' | 'disabled';

export interface SpeechToTextProvider {
  readonly id: string;
  readonly location: SpeechProviderLocation;
  readonly available: boolean;
  start(language: string): Promise<void>;
  stop(): Promise<string>;
  dispose(): void;
}

export interface TextToSpeechProvider {
  readonly id: string;
  readonly location: SpeechProviderLocation;
  readonly available: boolean;
  speak(text: string, language: string, onEnd: () => void, onError: (message: string) => void): void;
  stop(): void;
}

interface RecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}

interface RecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<RecognitionResultLike>;
}

interface RecognitionErrorLike {
  error: string;
}

interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEventLike) => void) | null;
  onerror: ((event: RecognitionErrorLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type RecognitionConstructor = new () => RecognitionLike;

function recognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  const speechWindow = window as Window & {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition || null;
}

export class BrowserSpeechToTextProvider implements SpeechToTextProvider {
  readonly id = 'browser-web-speech';
  readonly location = 'browser' as const;
  readonly available = recognitionConstructor() !== null;
  private recognition: RecognitionLike | null = null;
  private transcript = '';
  private resolveStop: ((text: string) => void) | null = null;
  private rejectStop: ((error: Error) => void) | null = null;

  async start(language: string): Promise<void> {
    const Constructor = recognitionConstructor();
    if (!Constructor) throw new Error('Browser speech recognition is not available.');
    this.dispose();
    this.transcript = '';
    const recognition = new Constructor();
    recognition.lang = language;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let next = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) next += result[0]?.transcript || '';
      }
      if (next.trim()) this.transcript = `${this.transcript} ${next}`.trim();
    };
    recognition.onerror = (event) => {
      this.rejectStop?.(new Error(`Microphone recognition failed (${event.error}).`));
      this.clearCallbacks();
    };
    recognition.onend = () => {
      this.resolveStop?.(this.transcript.trim());
      this.clearCallbacks();
      this.recognition = null;
    };
    this.recognition = recognition;
    recognition.start();
  }

  stop(): Promise<string> {
    if (!this.recognition) return Promise.reject(new Error('Microphone is not recording.'));
    return new Promise((resolve, reject) => {
      this.resolveStop = resolve;
      this.rejectStop = reject;
      this.recognition?.stop();
    });
  }

  dispose(): void {
    if (this.recognition) {
      this.recognition.onresult = null;
      this.recognition.onerror = null;
      this.recognition.onend = null;
      this.recognition.abort();
      this.recognition = null;
    }
    this.clearCallbacks();
    this.transcript = '';
  }

  private clearCallbacks(): void {
    this.resolveStop = null;
    this.rejectStop = null;
  }
}

export class LocalSpeechToTextProvider implements SpeechToTextProvider {
  readonly id: string;
  readonly location = 'local' as const;
  readonly available: boolean;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];

  constructor(id: string, available: boolean) {
    this.id = id || 'local-stt';
    this.available = available
      && typeof navigator !== 'undefined'
      && !!navigator.mediaDevices?.getUserMedia
      && typeof MediaRecorder !== 'undefined';
  }

  async start(_language: string): Promise<void> {
    if (!this.available) throw new Error('Local speech recognition is not available.');
    this.dispose();
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.recorder = new MediaRecorder(this.stream);
    this.chunks = [];
    this.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    };
    this.recorder.start();
  }

  stop(): Promise<string> {
    const recorder = this.recorder;
    if (!recorder || recorder.state !== 'recording') {
      return Promise.reject(new Error('Microphone is not recording.'));
    }
    return new Promise((resolve, reject) => {
      recorder.onstop = async () => {
        this.stopTracks();
        const chunks = this.chunks;
        this.chunks = [];
        this.recorder = null;
        try {
          const audio = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
          const result = await transcribeAudio(audio);
          resolve(result.text);
        } catch (error) {
          reject(error instanceof Error ? error : new Error('Transcription failed.'));
        }
      };
      recorder.stop();
    });
  }

  dispose(): void {
    const recorder = this.recorder;
    if (recorder && recorder.state !== 'inactive') {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.stop();
    }
    this.recorder = null;
    this.chunks = [];
    this.stopTracks();
  }

  private stopTracks(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}

export class DisabledSpeechToTextProvider implements SpeechToTextProvider {
  readonly id = 'disabled';
  readonly location = 'disabled' as const;
  readonly available = false;
  async start(): Promise<void> { throw new Error('Speech-to-text is disabled.'); }
  async stop(): Promise<string> { throw new Error('Speech-to-text is disabled.'); }
  dispose(): void {}
}

export class BrowserTextToSpeechProvider implements TextToSpeechProvider {
  readonly id = 'browser-speech-synthesis';
  readonly location = 'browser' as const;
  readonly available = typeof window !== 'undefined' && 'speechSynthesis' in window;

  speak(text: string, language: string, onEnd: () => void, onError: (message: string) => void): void {
    if (!this.available) {
      onError('Text-to-speech is not available.');
      return;
    }
    this.stop();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = language;
    utterance.onend = onEnd;
    utterance.onerror = () => onError('Text-to-speech failed.');
    window.speechSynthesis.speak(utterance);
  }

  stop(): void {
    if (this.available) window.speechSynthesis.cancel();
  }
}

export const LOCAL_AUDIO_START_EVENT = 'openjarvis:audio-start';
export const LOCAL_AUDIO_LEVEL_EVENT = 'openjarvis:audio-level';
export const LOCAL_AUDIO_END_EVENT = 'openjarvis:audio-end';

function sentenceChunks(text: string): string[] {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (!normalized) return [];
  const chunks = normalized.match(/[^.!?]+(?:[.!?]+|$)/g)?.map((part) => part.trim()) ?? [normalized];
  const bounded: string[] = [];
  for (const chunk of chunks) {
    if (chunk.length <= 450) bounded.push(chunk);
    else {
      for (let start = 0; start < chunk.length; start += 450) {
        bounded.push(chunk.slice(start, start + 450).trim());
      }
    }
  }
  return bounded.filter(Boolean);
}

function monotonicNow(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();
}

export class LocalTextToSpeechProvider implements TextToSpeechProvider {
  readonly id: string;
  readonly location = 'local' as const;
  readonly available: boolean;
  private generation = 0;
  private controller: AbortController | null = null;
  private audio: HTMLAudioElement | null = null;
  private objectUrl: string | null = null;
  private animationFrame: number | null = null;
  private audioContext: AudioContext | null = null;
  private active = false;

  constructor(id: string, available: boolean, private readonly fallback?: TextToSpeechProvider) {
    this.id = id || 'local-tts';
    this.available = available && typeof Audio !== 'undefined';
  }

  speak(text: string, language: string, onEnd: () => void, onError: (message: string) => void): void {
    if (!this.available) {
      if (this.fallback?.available) this.fallback.speak(text, language, onEnd, onError);
      else onError('Local text-to-speech is not available.');
      return;
    }
    this.stop();
    const generation = this.generation;
    const controller = new AbortController();
    const requestedAt = monotonicNow();
    this.controller = controller;
    this.active = true;
    void this.playStream(text, language, generation, controller.signal, requestedAt)
      .then((started) => {
        if (generation !== this.generation) return;
        this.controller = null;
        this.active = false;
        if (started && typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(LOCAL_AUDIO_END_EVENT));
        }
        onEnd();
      })
      .catch((error) => {
        if (controller.signal.aborted || generation !== this.generation) return;
        this.controller = null;
        const hadLocalActivity = this.active;
        this.active = false;
        this.cleanupAudioGraph();
        if (hadLocalActivity && typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(LOCAL_AUDIO_END_EVENT));
        }
        if (this.fallback?.available) {
          this.fallback.speak(text, language, onEnd, onError);
          return;
        }
        onError(error instanceof Error ? error.message : 'Local text-to-speech failed.');
      });
  }

  stop(): void {
    const hadActivity = this.active || this.controller !== null || this.audio !== null;
    this.generation += 1;
    this.controller?.abort();
    this.controller = null;
    this.audio?.pause();
    this.audio = null;
    this.active = false;
    this.cleanupAudioGraph();
    this.fallback?.stop();
    if (hadActivity && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(LOCAL_AUDIO_END_EVENT));
    }
  }

  private async playStream(
    text: string,
    language: string,
    generation: number,
    signal: AbortSignal,
    requestedAt: number,
  ): Promise<boolean> {
    const chunks = sentenceChunks(text);
    if (!chunks.length) return false;
    let started = false;
    let next = synthesizeSpeech(chunks[0], language, signal);
    for (let index = 0; index < chunks.length; index += 1) {
      const result = await next;
      if (signal.aborted || generation !== this.generation) return started;
      if (index + 1 < chunks.length) next = synthesizeSpeech(chunks[index + 1], language, signal);
      await this.playBlob(result.audio, generation, signal, () => {
        if (started || typeof window === 'undefined') return;
        started = true;
        window.dispatchEvent(new CustomEvent(LOCAL_AUDIO_START_EVENT, {
          detail: {
            backend: result.backend,
            requestToPlaybackMs: Math.max(monotonicNow() - requestedAt, 0),
          },
        }));
      });
    }
    return started;
  }

  private playBlob(
    blob: Blob,
    generation: number,
    signal: AbortSignal,
    onPlay: () => void,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const objectUrl = URL.createObjectURL(blob);
      const audio = new Audio(objectUrl);
      this.objectUrl = objectUrl;
      this.audio = audio;
      audio.onplay = () => {
        onPlay();
        this.startAudioLevels(audio);
      };
      audio.onended = () => {
        this.cleanupAudioGraph();
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(LOCAL_AUDIO_LEVEL_EVENT, { detail: { level: 0 } }));
        }
        if (generation === this.generation) this.audio = null;
        resolve();
      };
      audio.onerror = () => {
        this.cleanupAudioGraph();
        this.audio = null;
        reject(new Error('Local audio playback failed.'));
      };
      signal.addEventListener('abort', () => {
        audio.pause();
        this.cleanupAudioGraph();
        this.audio = null;
        resolve();
      }, { once: true });
      void audio.play().catch(reject);
    });
  }

  private startAudioLevels(audio: HTMLAudioElement): void {
    const AudioContextClass = window.AudioContext;
    if (!AudioContextClass) return;
    try {
      const context = new AudioContextClass();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      context.createMediaElementSource(audio).connect(analyser);
      analyser.connect(context.destination);
      const values = new Uint8Array(analyser.fftSize);
      let envelope = 0;
      const sample = () => {
        analyser.getByteTimeDomainData(values);
        const meanSquare = values.reduce((sum, value) => {
          const normalized = (value - 128) / 128;
          return sum + normalized * normalized;
        }, 0) / values.length;
        const target = Math.min(1, Math.max(0, Math.sqrt(meanSquare) - 0.012) * 5.2);
        envelope = target >= envelope
          ? envelope * 0.35 + target * 0.65
          : envelope * 0.72 + target * 0.28;
        window.dispatchEvent(new CustomEvent(LOCAL_AUDIO_LEVEL_EVENT, {
          detail: { level: envelope },
        }));
        if (!audio.paused && !audio.ended) this.animationFrame = requestAnimationFrame(sample);
      };
      this.audioContext = context;
      sample();
    } catch {
      // Playback remains functional when the WebView denies WebAudio analysis.
    }
  }

  private cleanupAudioGraph(): void {
    if (this.animationFrame !== null) cancelAnimationFrame(this.animationFrame);
    this.animationFrame = null;
    void this.audioContext?.close().catch(() => {});
    this.audioContext = null;
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
  }
}

export class DisabledTextToSpeechProvider implements TextToSpeechProvider {
  readonly id = 'disabled';
  readonly location = 'disabled' as const;
  readonly available = false;
  speak(_text: string, _language: string, _onEnd: () => void, onError: (message: string) => void): void {
    onError('Text-to-speech is disabled.');
  }
  stop(): void {}
}
