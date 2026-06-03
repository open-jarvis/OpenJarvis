export type WakeMode =
  | 'idle'
  | 'wake'
  | 'detected'
  | 'command'
  | 'sending'
  | 'error';

export const WAKE_PHRASES = [
  'friday',
  'hey friday',
  '프라이데이',
  '헤이 프라이데이',
];

export type LocalWakeStep =
  | { action: 'none'; awaitingCommand: boolean; lastDetectedAt: number }
  | { action: 'duplicate_wake'; awaitingCommand: boolean; lastDetectedAt: number }
  | { action: 'wake_detected'; awaitingCommand: true; lastDetectedAt: number }
  | { action: 'command_ready'; command: string; awaitingCommand: false; lastDetectedAt: number };

export const WAKE_DEBOUNCE_MS = 3000;

export function shouldRunLocalWakeLoop({
  wakeListening,
  speechEnabled,
  appMode,
  documentHidden,
}: {
  wakeListening: boolean;
  speechEnabled: boolean;
  appMode: boolean;
  documentHidden: boolean;
}): boolean {
  return wakeListening && speechEnabled && appMode && !documentHidden;
}

export function isLocalWakeLoopStopped({
  stopped,
  aborted,
}: {
  stopped: boolean;
  aborted: boolean;
}): boolean {
  return stopped || aborted;
}

export function shouldContinueLocalWakeLoop({
  wakeListening,
  stopRequested,
  aborted,
}: {
  wakeListening: boolean;
  stopRequested: boolean;
  aborted: boolean;
}): boolean {
  return wakeListening && !stopRequested && !aborted;
}

export function nextWakeStatusAfterCommand({
  wakeListening,
  stopRequested,
  aborted,
}: {
  wakeListening: boolean;
  stopRequested: boolean;
  aborted: boolean;
}): 'wake' | 'stopped' {
  return shouldContinueLocalWakeLoop({ wakeListening, stopRequested, aborted })
    ? 'wake'
    : 'stopped';
}

export function hasWakePhrase(text: string): boolean {
  return hasWakePhraseFromList(text, WAKE_PHRASES);
}

export function normalizeWakePhrases(phrases: string[] | string | undefined): string[] {
  const raw = Array.isArray(phrases)
    ? phrases
    : String(phrases || '').split(/[,;\n]/);
  const cleaned = raw.map((phrase) => phrase.trim()).filter(Boolean);
  return Array.from(new Set([...cleaned, ...WAKE_PHRASES]));
}

export function hasWakePhraseFromList(text: string, phrases?: string[]): boolean {
  const normalized = text.trim().toLowerCase();
  return normalizeWakePhrases(phrases).some((phrase) =>
    normalized.includes(phrase.toLowerCase()),
  );
}

export function stripWakePhrase(text: string): string {
  return stripWakePhraseFromList(text, WAKE_PHRASES);
}

export function stripWakePhraseFromList(text: string, phrases?: string[]): string {
  let cleaned = text.trim();
  for (const phrase of normalizeWakePhrases(phrases).sort((a, b) => b.length - a.length)) {
    cleaned = cleaned.replace(new RegExp(escapeRegExp(phrase), 'gi'), ' ');
  }
  return cleaned.replace(/\s+/g, ' ').trim();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function evaluateLocalWakeText(
  text: string,
  {
    awaitingCommand,
    lastDetectedAt,
    now,
    debounceMs = WAKE_DEBOUNCE_MS,
    wakePhrases,
  }: {
    awaitingCommand: boolean;
    lastDetectedAt: number;
    now: number;
    debounceMs?: number;
    wakePhrases?: string[];
  },
): LocalWakeStep {
  const trimmed = text.trim();
  if (!trimmed) {
    return { action: 'none', awaitingCommand: false, lastDetectedAt };
  }

  if (awaitingCommand) {
    const command = hasWakePhraseFromList(trimmed, wakePhrases)
      ? stripWakePhraseFromList(trimmed, wakePhrases)
      : trimmed;
    if (!command) {
      return { action: 'none', awaitingCommand: true, lastDetectedAt };
    }
    return {
      action: 'command_ready',
      command,
      awaitingCommand: false,
      lastDetectedAt,
    };
  }

  if (!hasWakePhraseFromList(trimmed, wakePhrases)) {
    return { action: 'none', awaitingCommand: false, lastDetectedAt };
  }
  if (now - lastDetectedAt < debounceMs) {
    return { action: 'duplicate_wake', awaitingCommand: false, lastDetectedAt };
  }
  return {
    action: 'wake_detected',
    awaitingCommand: true,
    lastDetectedAt: now,
  };
}
