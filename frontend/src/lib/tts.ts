// Tiny wrapper around the browser's SpeechSynthesis API.
// Buffers streamed tokens and speaks on sentence boundaries.
//
// Public API:
//   speak(text)              - speak a single utterance now
//   onTokenStream(delta)     - feed a streamed token; speak when buffer
//                              hits a sentence boundary
//   flush()                  - speak any remaining buffered text
//   cancel()                 - stop speaking and clear queue
//   isSupported()            - true if window.speechSynthesis exists

const SENTENCE_END = /[.!?\n]\s*$/;
// Don't speak if buffer is too short — wait for more tokens.
const MIN_FLUSH_LEN = 12;

let buffer = '';

export function isSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

function pickVoice(): SpeechSynthesisVoice | null {
  if (!isSupported()) return null;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;
  const lang = (navigator.language || 'en-US').toLowerCase();
  const langPrefix = lang.split('-')[0];
  // Prefer local voices in the user's language
  const local = voices.find(
    (v) => v.localService && v.lang.toLowerCase().startsWith(langPrefix),
  );
  if (local) return local;
  // Fallback: any voice in the user's language
  const anyLang = voices.find((v) => v.lang.toLowerCase().startsWith(langPrefix));
  if (anyLang) return anyLang;
  // Last resort: first available
  return voices[0] ?? null;
}

function enqueue(text: string): void {
  if (!isSupported() || !text.trim()) return;
  const u = new SpeechSynthesisUtterance(text);
  const voice = pickVoice();
  if (voice) u.voice = voice;
  u.rate = 1.0;
  u.pitch = 1.0;
  u.volume = 1.0;
  window.speechSynthesis.speak(u);
}

export function speak(text: string): void {
  if (!isSupported()) return;
  enqueue(text);
}

export function onTokenStream(delta: string): void {
  if (!isSupported() || !delta) return;
  buffer += delta;
  // Flush whenever we cross a sentence boundary AND have enough characters.
  if (SENTENCE_END.test(buffer) && buffer.trim().length >= MIN_FLUSH_LEN) {
    const toSpeak = buffer;
    buffer = '';
    enqueue(toSpeak);
  }
}

export function flush(): void {
  if (!isSupported()) return;
  if (buffer.trim()) {
    const toSpeak = buffer;
    buffer = '';
    enqueue(toSpeak);
  }
}

export function cancel(): void {
  if (!isSupported()) return;
  buffer = '';
  window.speechSynthesis.cancel();
}

export function isSpeaking(): boolean {
  return isSupported() && window.speechSynthesis.speaking;
}
