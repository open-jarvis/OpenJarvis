/**
 * Texto para la voz del HUD: detección de la palabra de activación en una
 * transcripción y corte incremental de la respuesta en frases pronunciables.
 */
import { toSpeakableText } from '../message-text';

export interface WakeWordMatch {
  matched: boolean;
  /** La orden sin el nombre; vacía si solo se dijo "Jarvis". */
  command: string;
}

// Whisper no conoce el nombre y lo escribe según lo oye: la consonante inicial
// ("Yarvis", "Carvis", "Harbys", "Charvis"), la vocal ("Jervis") y el final
// ("Jarbiz", "Jarvys") varían; se acepta el patrón fonético completo.
// Los límites con \p{L}\p{N} evitan activar con palabras que solo lo contienen.
const WAKE_WORD =
  /(?<![\p{L}\p{N}])(?:(?:hey|ey|oye|ok|okay|hola)[\s,]+)?(?:ch|[jyhgck])[aáe]r[vb][iíy][sz](?![\p{L}\p{N}])/iu;

const NO_MATCH: WakeWordMatch = { matched: false, command: '' };

export function matchWakeWord(transcript: string): WakeWordMatch {
  const match = WAKE_WORD.exec(transcript);
  if (!match) return NO_MATCH;

  // Se quita el nombre junto con la puntuación que lo separaba del resto.
  const before = transcript.slice(0, match.index).replace(/[\s,;:.-]+$/u, '');
  const after = transcript.slice(match.index + match[0].length).replace(/^[\s,;:.!-]+/u, '');
  const needsSpace = before !== '' && /^[\p{L}\p{N}¿¡]/u.test(after);
  const command = `${before}${needsSpace ? ' ' : ''}${after}`.trim();

  // "¿Jarvis?" deja solo signos: equivale a decir únicamente el nombre.
  return { matched: true, command: /[\p{L}\p{N}]/u.test(command) ? command : '' };
}

/** Las frases más cortas se unen a la siguiente para no entrecortar la voz. */
const MIN_CHUNK_CHARS = 20;

const SENTENCE_END = /[.!?…]+["')\]»]*\s+|\n+/g;
const CLOSED_THINK = /<think>[\s\S]*?<\/think>/gi;
const CLOSED_FENCE = /```[\s\S]*?```/g;

export interface SentenceSplitter {
  /** Agrega texto recién llegado y devuelve las frases que ya se pueden decir. */
  push(delta: string): string[];
  /** Devuelve lo que quedó pendiente al terminar la respuesta. */
  flush(): string[];
}

/**
 * El código y el razonamiento interno no se leen en voz alta: los bloques
 * cerrados se descartan y uno abierto detiene el corte hasta que cierre.
 */
export function createSentenceSplitter(): SentenceSplitter {
  let buffer = '';

  const dropSilentBlocks = () => {
    buffer = buffer.replace(CLOSED_THINK, '').replace(CLOSED_FENCE, '\n');
  };

  /** Longitud del tramo inicial que no cae dentro de un bloque todavía abierto. */
  const safeLength = (): number => {
    const openings = [buffer.indexOf('<think>'), buffer.indexOf('```')].filter((i) => i >= 0);
    return openings.length > 0 ? Math.min(...openings) : buffer.length;
  };

  const push = (delta: string): string[] => {
    buffer += delta;
    dropSilentBlocks();

    const sentences: string[] = [];
    const limit = safeLength();
    let chunkStart = 0;

    SENTENCE_END.lastIndex = 0;
    let boundary: RegExpExecArray | null;
    while ((boundary = SENTENCE_END.exec(buffer)) !== null) {
      const chunkEnd = boundary.index + boundary[0].length;
      if (chunkEnd > limit) break;

      const speakable = toSpeakableText(buffer.slice(chunkStart, chunkEnd));
      if (speakable.length < MIN_CHUNK_CHARS) continue;
      sentences.push(speakable);
      chunkStart = chunkEnd;
    }

    buffer = buffer.slice(chunkStart);
    return sentences;
  };

  const flush = (): string[] => {
    dropSilentBlocks();
    // Un bloque que nunca cerró no se pronuncia.
    const speakable = toSpeakableText(buffer.slice(0, safeLength()));
    buffer = '';
    return speakable ? [speakable] : [];
  };

  return { push, flush };
}
