/**
 * Spoken-language helpers for the HUD: which language Whisper listens for,
 * which language Jarvis answers in, and which browser voice reads Malayalam.
 */

export type SpeechLang = 'auto' | 'en' | 'ml';

export const SPEECH_LANG_LABEL: Record<SpeechLang, string> = {
  auto: 'AUTO',
  en: 'EN',
  ml: 'മലയാളം',
};

const ORDER: SpeechLang[] = ['auto', 'en', 'ml'];

export function nextSpeechLang(lang: SpeechLang): SpeechLang {
  return ORDER[(ORDER.indexOf(lang) + 1) % ORDER.length];
}

export function isSpeechLang(value: unknown): value is SpeechLang {
  return value === 'auto' || value === 'en' || value === 'ml';
}

const MALAYALAM_CHAR = /[ഀ-ൿ]/g;
const LATIN_CHAR = /[A-Za-z]/g;
/** Share of letters that must be Malayalam for the text to count as Malayalam. */
const MALAYALAM_SHARE = 0.3;

/** True when the text is mostly Malayalam script (a few English words allowed). */
export function hasMalayalam(text: string): boolean {
  const ml = text.match(MALAYALAM_CHAR)?.length ?? 0;
  if (ml === 0) return false;
  const latin = text.match(LATIN_CHAR)?.length ?? 0;
  return ml / (ml + latin) >= MALAYALAM_SHARE;
}

/** Language code to force in Whisper, or undefined to let it detect. */
export function whisperLanguage(lang: SpeechLang): string | undefined {
  return lang === 'auto' ? undefined : lang;
}

/**
 * Instruction attached to a spoken turn. Small local models follow a rule on
 * the question itself far better than one buried in the system prompt.
 */
export function spokenReplySuffix(lang: SpeechLang, heard: string): string {
  const malayalam = lang === 'ml' || (lang === 'auto' && hasMalayalam(heard));
  const language = malayalam
    ? ' Reply in Malayalam, written in Malayalam script.'
    : lang === 'en'
      ? ' Reply in English.'
      : '';
  return (
    '\n\n(Spoken request: reply in at most two short spoken sentences, plain words, ' +
    `no lists or markdown.${language})`
  );
}

/**
 * Best browser voice for Malayalam. Edge ships Microsoft's natural voices
 * ("Midhun" male, "Sobhana" female); prefer the male one to match Jarvis.
 */
export function pickMalayalamVoice(
  voices: readonly Pick<SpeechSynthesisVoice, 'name' | 'lang'>[],
): SpeechSynthesisVoice | null {
  const ml = voices.filter((v) => v.lang.toLowerCase().startsWith('ml'));
  const found =
    ml.find((v) => /midhun/i.test(v.name)) ??
    ml.find((v) => /natural|online/i.test(v.name)) ??
    ml[0] ??
    null;
  return found as SpeechSynthesisVoice | null;
}
