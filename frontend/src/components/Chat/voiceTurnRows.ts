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
