export interface PlayableAudioSegment {
  audio: string;
  mime: string;
  text?: string;
  turnId?: number;
}

export interface VoiceAudioElement {
  src: string;
  onended: ((event: Event) => void) | null;
  play: () => Promise<void>;
  pause: () => void;
}

export class VoicePlaybackQueue {
  private readonly queue: PlayableAudioSegment[] = [];
  private current: VoiceAudioElement | null = null;

  constructor(
    private readonly createAudio: (src: string) => VoiceAudioElement = (src) => new Audio(src),
    private readonly onPlaying: (playing: boolean) => void = () => undefined,
    private readonly onSegmentPlayed: (segment: PlayableAudioSegment) => void = () => undefined,
    private readonly onSegmentStarted: (segment: PlayableAudioSegment) => void = () => undefined,
  ) {}

  enqueue(segment: PlayableAudioSegment): void {
    this.queue.push(segment);
    this.playNext();
  }

  stop(): void {
    this.queue.length = 0;
    if (this.current) {
      this.current.onended = null;
      this.current.pause();
      this.current.src = '';
      this.current = null;
    }
    this.onPlaying(false);
  }

  isPlaying(): boolean {
    return this.current !== null;
  }

  private playNext(): void {
    if (this.current) return;
    const segment = this.queue.shift();
    if (!segment) {
      this.onPlaying(false);
      return;
    }

    const audio = this.createAudio(`data:${segment.mime};base64,${segment.audio}`);
    this.current = audio;
    this.onSegmentStarted(segment);
    this.onPlaying(true);
    audio.onended = () => {
      this.onSegmentPlayed(segment);
      audio.src = '';
      this.current = null;
      this.playNext();
    };
    void audio.play().catch(() => audio.onended?.(new Event('ended')));
  }
}
