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
  '프라이데',
  '헤이 프라이데이',
];

export function hasWakePhrase(text: string): boolean {
  const normalized = text.trim().toLowerCase();
  return WAKE_PHRASES.some((phrase) => normalized.includes(phrase));
}

export function stripWakePhrase(text: string): string {
  let cleaned = text.trim();
  for (const phrase of WAKE_PHRASES) {
    cleaned = cleaned.replace(new RegExp(escapeRegExp(phrase), 'gi'), ' ');
  }
  return cleaned.replace(/\s+/g, ' ').trim();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
