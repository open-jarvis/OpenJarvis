/**
 * Wake-word matching on transcripts.
 *
 * Hands-free mode transcribes every utterance and only acts on the ones that
 * address the assistant by name: "Jarvis, what's the weather?", "Hey Jarvis",
 * or "What time is it, Jarvis?". Whisper spells a name inconsistently
 * ("Jarvis", "Jervis", "Javis"), so the match tolerates one edit.
 */

const LEADING_FILLERS = new Set(['hey', 'hi', 'ok', 'okay', 'yo', 'so', 'um', 'uh', 'oh', 'and', 'hello', 'excuse', 'me']);

// A dismissal is an optional acknowledgement ("ok", "thanks"), an optional
// closing phrase ("that's all", "I'm done"), and an optional "for now", in any
// combination, but at least one of the first two. Matched against normalized
// text, where the wake word has been replaced by "jarvis".
const DISMISSAL =
  /^(?:(?:ok|okay|alright|all right|great|perfect|cool|got it|good)\s+)?(?:(?:thanks|thank you|thank you very much|thanks a lot|cheers|appreciate it)(?:\s+so much)?)?(?:\s*jarvis)?(?:\s*(?:that s all|that is all|that ll be all|that will be all|that s it|that is it|i m good|i m done|i m all set|we re done|we are done|all good|nothing else|no more questions|never mind|nevermind|go to sleep|goodbye|good bye|bye|bye bye|cancel|stop listening|no thanks|no thank you|nothing))?(?:\s+for now)?(?:\s+jarvis)?$/;
const ACK_OR_CLOSE = /\b(?:thanks|thank you|cheers|appreciate|that s all|that is all|that ll be all|that will be all|that s it|that is it|i m good|i m done|i m all set|we re done|we are done|all good|nothing else|no more questions|never mind|nevermind|go to sleep|goodbye|good bye|bye|cancel|stop listening|no thanks|no thank you|nothing)\b/;

const STOPS = new Set(['stop', 'stop it', 'stop talking', 'be quiet', 'quiet', 'shut up', 'enough', 'pause', 'hold on', 'wait']);

/** Lowercase, drop punctuation, collapse whitespace ("That's all." -> "that s all"). */
export function normalizeSpeech(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

function editDistance(a: string, b: string): number {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
  }
  return dp[a.length][b.length];
}

/** True when a single spoken word is the wake word (allowing one edit for longer names). */
export function isWakeToken(word: string, wakeWord: string): boolean {
  const w = normalizeSpeech(word).replace(/ s$/, '').replace(/\s+/g, '');
  const target = normalizeSpeech(wakeWord).replace(/\s+/g, '');
  if (!w || !target) return false;
  if (w === target) return true;
  return target.length >= 5 && Math.abs(w.length - target.length) <= 1 && editDistance(w, target) <= 1;
}

export interface WakeMatch {
  /** The utterance addressed the assistant. */
  woke: boolean;
  /** What was said besides the wake word, original casing kept ("" if just the name). */
  command: string;
}

function tidy(words: string[]): string {
  const text = words
    .join(' ')
    .replace(/^[\s,.;:!?-]+/, '')
    .replace(/\s+([,.;:!?])/g, '$1')
    .replace(/,([.?!])/g, '$1')
    .replace(/[,;:\s-]+$/, '')
    .trim();
  return text ? text[0].toUpperCase() + text.slice(1) : '';
}

/**
 * Find the wake word at the start (after fillers like "hey"/"ok") or at the end
 * of an utterance, and return the rest as the command.
 */
export function parseWakeCommand(transcript: string, wakeWord = 'jarvis'): WakeMatch {
  const words = transcript.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return { woke: false, command: '' };

  // Leading: "Jarvis, ...", "Hey Jarvis ...", "Okay, so, Jarvis ...".
  for (let i = 0; i < Math.min(words.length, 4); i++) {
    if (isWakeToken(words[i], wakeWord)) {
      return { woke: true, command: tidy(words.slice(i + 1)) };
    }
    if (!LEADING_FILLERS.has(normalizeSpeech(words[i]))) break;
  }

  // Trailing: "What time is it, Jarvis?"
  const last = words[words.length - 1];
  if (words.length > 1 && isWakeToken(last, wakeWord)) {
    const terminal = /[?!.]$/.test(last) ? last.slice(-1) : '';
    const rest = words.slice(0, -1);
    const body = tidy(rest);
    return { woke: true, command: body && terminal && !/[?!.]$/.test(body) ? body + terminal : body };
  }

  return { woke: false, command: '' };
}

/** "Thanks", "that's all", "never mind": end the conversation and go back to waiting. */
export function isDismissal(command: string, wakeWord = 'jarvis'): boolean {
  const wake = normalizeSpeech(wakeWord);
  const t = normalizeSpeech(command)
    .split(' ')
    .map((w) => (wake && isWakeToken(w, wake) ? 'jarvis' : w))
    .join(' ');
  return t !== '' && DISMISSAL.test(t) && ACK_OR_CLOSE.test(t);
}

/** "Stop", "be quiet": cut off the current reply. */
export function isStopCommand(command: string): boolean {
  return STOPS.has(normalizeSpeech(command));
}

/**
 * Whisper invents short phrases from noise or silence ("Thank you.", "you").
 * These are never treated as follow-up questions.
 */
export function isLikelyHallucination(transcript: string): boolean {
  const t = normalizeSpeech(transcript);
  return (
    t === '' ||
    t === 'you' ||
    t === 'thank you for watching' ||
    t === 'thanks for watching' ||
    t === 'please subscribe' ||
    t.length < 2
  );
}
