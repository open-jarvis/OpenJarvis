export type JarvisVoiceState =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'speaking'
  | 'interrupted'
  | 'error'
  | 'offline'
  | 'reconnecting';

export type MicrophoneState = 'unavailable' | 'off' | 'on' | 'processing' | 'error';
export type PlaybackState = 'idle' | 'playing' | 'paused' | 'interrupted' | 'error';

export interface VoiceAdapterSnapshot {
  state: JarvisVoiceState;
  microphoneState: MicrophoneState;
  playbackState: PlaybackState;
  volumeLevel: number;
  speakingProgress: number | null;
  transcriptReady: boolean;
  errorMessage: string | null;
  interruptRequested: boolean;
  updatedAt: number;
}

export interface VoiceStateAdapter {
  readonly id: string;
  getSnapshot(): VoiceAdapterSnapshot;
  subscribe(listener: (snapshot: VoiceAdapterSnapshot) => void): () => void;
  startListening(): void;
  stopListening(): void;
  cancelListening(): void;
  interruptSpeech(): void;
  startNewConversation(): void;
  dispose(): void;
}

export const DEFAULT_VOICE_SNAPSHOT: VoiceAdapterSnapshot = {
  state: 'idle',
  microphoneState: 'off',
  playbackState: 'idle',
  volumeLevel: 0,
  speakingProgress: null,
  transcriptReady: false,
  errorMessage: null,
  interruptRequested: false,
  updatedAt: 0,
};

export function clampVoiceLevel(level: number): number {
  if (!Number.isFinite(level)) return 0;
  return Math.min(1, Math.max(0, level));
}

export function deriveVoiceSnapshot(input: {
  recording: boolean;
  processing: boolean;
  speaking: boolean;
  sttAvailable: boolean;
  streamStatus: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'offline';
  errorMessage?: string | null;
  volumeLevel?: number;
}): VoiceAdapterSnapshot {
  const now = Date.now();
  if (input.errorMessage) {
    return {
      ...DEFAULT_VOICE_SNAPSHOT,
      state: 'error',
      microphoneState: input.recording ? 'error' : input.sttAvailable ? 'off' : 'unavailable',
      playbackState: input.speaking ? 'error' : 'idle',
      errorMessage: input.errorMessage,
      updatedAt: now,
    };
  }
  if (input.streamStatus === 'offline') {
    return {
      ...DEFAULT_VOICE_SNAPSHOT,
      state: 'offline',
      microphoneState: input.sttAvailable ? 'off' : 'unavailable',
      updatedAt: now,
    };
  }
  if (input.streamStatus === 'reconnecting' || input.streamStatus === 'connecting') {
    return {
      ...DEFAULT_VOICE_SNAPSHOT,
      state: 'reconnecting',
      microphoneState: input.sttAvailable ? 'off' : 'unavailable',
      updatedAt: now,
    };
  }
  if (input.recording) {
    return {
      ...DEFAULT_VOICE_SNAPSHOT,
      state: 'listening',
      microphoneState: 'on',
      volumeLevel: clampVoiceLevel(input.volumeLevel ?? 0),
      updatedAt: now,
    };
  }
  if (input.processing) {
    return {
      ...DEFAULT_VOICE_SNAPSHOT,
      state: 'processing',
      microphoneState: input.sttAvailable ? 'processing' : 'unavailable',
      updatedAt: now,
    };
  }
  if (input.speaking) {
    return {
      ...DEFAULT_VOICE_SNAPSHOT,
      state: 'speaking',
      microphoneState: input.sttAvailable ? 'off' : 'unavailable',
      playbackState: 'playing',
      volumeLevel: clampVoiceLevel(input.volumeLevel ?? 0),
      updatedAt: now,
    };
  }
  return {
    ...DEFAULT_VOICE_SNAPSHOT,
    microphoneState: input.sttAvailable ? 'off' : 'unavailable',
    updatedAt: now,
  };
}

/** Development-only adapter. It never captures, synthesizes, or plays audio. */
export class MockVoiceAdapter implements VoiceStateAdapter {
  readonly id = 'jarvis-voice-mock';
  private snapshot: VoiceAdapterSnapshot = { ...DEFAULT_VOICE_SNAPSHOT, updatedAt: Date.now() };
  private listeners = new Set<(snapshot: VoiceAdapterSnapshot) => void>();
  private speakingTimer: ReturnType<typeof setInterval> | null = null;
  private speakingPhase = 0;

  getSnapshot(): VoiceAdapterSnapshot {
    return this.snapshot;
  }

  subscribe(listener: (snapshot: VoiceAdapterSnapshot) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot);
    return () => this.listeners.delete(listener);
  }

  setState(state: JarvisVoiceState): void {
    this.stopSpeakingTimer();
    const base: VoiceAdapterSnapshot = {
      ...DEFAULT_VOICE_SNAPSHOT,
      state,
      microphoneState: state === 'listening' ? 'on' : state === 'processing' ? 'processing' : 'off',
      playbackState: state === 'speaking' ? 'playing' : state === 'interrupted' ? 'interrupted' : 'idle',
      transcriptReady: state === 'processing',
      errorMessage: state === 'error' ? 'Simulierter, benutzerfreundlicher Sprachfehler.' : null,
      interruptRequested: state === 'interrupted',
      updatedAt: Date.now(),
    };
    this.publish(base);
    if (state === 'speaking') this.startSpeakingTimer();
  }

  setVolume(level: number): void {
    this.publish({
      ...this.snapshot,
      volumeLevel: clampVoiceLevel(level),
      updatedAt: Date.now(),
    });
  }

  startListening(): void {
    this.setState('listening');
  }

  stopListening(): void {
    this.setState('processing');
  }

  cancelListening(): void {
    this.setState('idle');
  }

  interruptSpeech(): void {
    this.setState('interrupted');
  }

  startNewConversation(): void {
    this.setState('idle');
  }

  dispose(): void {
    this.stopSpeakingTimer();
    this.listeners.clear();
  }

  private startSpeakingTimer(): void {
    this.speakingPhase = 0;
    this.speakingTimer = setInterval(() => {
      this.speakingPhase += 0.62;
      const envelope = 0.18 + Math.abs(Math.sin(this.speakingPhase)) * 0.52;
      const detail = Math.abs(Math.sin(this.speakingPhase * 2.37)) * 0.18;
      this.setVolume(envelope + detail);
    }, 90);
  }

  private stopSpeakingTimer(): void {
    if (this.speakingTimer !== null) clearInterval(this.speakingTimer);
    this.speakingTimer = null;
  }

  private publish(snapshot: VoiceAdapterSnapshot): void {
    this.snapshot = snapshot;
    this.listeners.forEach((listener) => listener(snapshot));
  }
}
