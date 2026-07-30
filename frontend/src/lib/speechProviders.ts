import { transcribeAudio } from './api';

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

export class DisabledTextToSpeechProvider implements TextToSpeechProvider {
  readonly id = 'disabled';
  readonly location = 'disabled' as const;
  readonly available = false;
  speak(_text: string, _language: string, _onEnd: () => void, onError: (message: string) => void): void {
    onError('Text-to-speech is disabled.');
  }
  stop(): void {}
}
