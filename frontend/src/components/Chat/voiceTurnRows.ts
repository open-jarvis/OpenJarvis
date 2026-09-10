export type VoiceTurnRow = {
  role: 'error' | 'user' | 'assistant';
  text: string;
};

export function assistantCaptionDelta(previous: string, next: string): string {
  if (!next.startsWith(previous)) return '';
  return next.slice(previous.length).trim();
}

export function splitCaptionSegments(text: string): string[] {
  const normalized = text.trim();
  return normalized ? normalized.split(/(?<=[.!?…])\s+/u) : [];
}

export interface CaptionDisplaySegments {
  completedText: string;
  activeText: string;
}

export function partitionCaptionSegments(text: string): CaptionDisplaySegments {
  const trimmed = text.trim();
  if (!trimmed) return { completedText: '', activeText: '' };
  const segments = splitCaptionSegments(trimmed);
  if (segments.length <= 1) {
    return { completedText: '', activeText: trimmed };
  }
  const activeText = segments[segments.length - 1] ?? '';
  const completedText = trimmed.slice(0, trimmed.length - activeText.length).trimEnd();
  return { completedText, activeText };
}


export function voiceCaptionHoldMs(text: string): number {
  return Math.min(5_000, Math.max(900, Math.round(text.length * 65)));
}

export function nextCaptionSegment(
  pending: readonly string[],
  current: string,
  elapsedMs = Number.POSITIVE_INFINITY,
  minimumHoldMs = 0,
): { pending: string[]; current: string } {
  if (current && elapsedMs < minimumHoldMs) {
    return { pending: [...pending], current };
  }
  const [next, ...remaining] = pending;
  return next ? { pending: remaining, current: next } : { pending: [], current };
}

export function currentVoiceTurnRows({
  transcript,
  assistantText,
  error,
}: {
  transcript: string;
  assistantText: string;
  error: string | null;
}): VoiceTurnRow[] {
  return [
    error && { role: 'error' as const, text: error },
    transcript && { role: 'user' as const, text: transcript },
    assistantText && { role: 'assistant' as const, text: assistantText },
  ].filter((row): row is VoiceTurnRow => Boolean(row));
}

export interface SpeechToken {
  text: string;
  delayMs: number;
}

export function tokenizeSpeechPacing(text: string, msPerChar = 55): SpeechToken[] {
  if (!text) return [];
  const rawTokens = text.match(/\S+\s*/gu) ?? [];
  return rawTokens.map((token) => {
    const trimmed = token.trim();
    let pause = 0;
    if (/[.!?…]$/u.test(trimmed)) {
      pause = 200;
    } else if (/[,;:]$/u.test(trimmed)) {
      pause = 100;
    }
    const delayMs = Math.max(160, Math.min(450, Math.round(trimmed.length * msPerChar + pause)));
    return { text: token, delayMs };
  });
}

export class SpeechPacer {
  private queue: SpeechToken[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private onToken: (text: string) => void;
  private onComplete?: () => void;

  constructor(onToken: (text: string) => void, onComplete?: () => void) {
    this.onToken = onToken;
    this.onComplete = onComplete;
  }

  enqueue(text: string, msPerChar = 55): void {
    const tokens = tokenizeSpeechPacing(text, msPerChar);
    if (tokens.length === 0) return;
    this.queue.push(...tokens);
    if (!this.timer) {
      this.tick();
    }
  }

  private tick(): void {
    if (this.queue.length === 0) {
      this.timer = null;
      this.onComplete?.();
      return;
    }
    const token = this.queue.shift()!;
    this.onToken(token.text);
    this.timer = setTimeout(() => {
      this.tick();
    }, token.delayMs);
  }

  flush(): string {
    const remaining = this.queue.map((t) => t.text).join('');
    this.cancel();
    return remaining;
  }

  cancel(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.queue = [];
  }

  isBusy(): boolean {
    return this.queue.length > 0 || this.timer !== null;
  }
}

