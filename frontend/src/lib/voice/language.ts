/**
 * Language hint for hands-free transcription.
 *
 * Whisper detects the language from the audio, but on a one-second clip such
 * as a bare "Jarvis" its guess is close to random (it was measured at 10-54%
 * confidence, and "Jarvis" came back in Greek). Telling it the language makes
 * short commands reliable.
 */

/** Languages offered in Settings, besides "match system" and auto-detect. */
export const VOICE_LANGUAGES: Array<[code: string, name: string]> = [
  ['en', 'English'],
  ['ar', 'Arabic'],
  ['zh', 'Chinese'],
  ['da', 'Danish'],
  ['nl', 'Dutch'],
  ['fi', 'Finnish'],
  ['fr', 'French'],
  ['de', 'German'],
  ['hi', 'Hindi'],
  ['it', 'Italian'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
  ['no', 'Norwegian'],
  ['fa', 'Persian'],
  ['pl', 'Polish'],
  ['pt', 'Portuguese'],
  ['ru', 'Russian'],
  ['es', 'Spanish'],
  ['sv', 'Swedish'],
  ['tr', 'Turkish'],
  ['uk', 'Ukrainian'],
];

/** Base language of the system/browser locale ("en-US" -> "en"), if known. */
export function systemLanguage(locale = typeof navigator !== 'undefined' ? navigator.language : ''): string {
  const base = (locale || '').split('-')[0].toLowerCase();
  return /^[a-z]{2,3}$/.test(base) ? base : '';
}

/**
 * Resolve the `voiceLanguage` setting to the code sent with transcriptions,
 * or undefined to let the backend auto-detect.
 */
export function resolveVoiceLanguage(setting: string, locale?: string): string | undefined {
  if (setting === 'auto') return undefined;
  if (setting) return setting;
  return systemLanguage(locale) || undefined;
}
