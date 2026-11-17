/**
 * Elección de la voz del navegador para Jarvis.
 *
 * Edge trae voces neuronales en español ("Online (Natural)") que suenan bien,
 * responden al instante y no cuestan nada: son la opción por defecto del HUD.
 */

/** Lo mínimo de `SpeechSynthesisVoice` que necesita la elección (facilita las pruebas). */
export interface VoiceInfo {
  name: string;
  lang: string;
  localService: boolean;
}

// Preferencia por país: el español de Colombia primero, luego los más cercanos.
const REGION_SCORES: Record<string, number> = {
  co: 30,
  mx: 20,
  us: 15,
  ar: 12,
  es: 10,
};
/** Nombres de voces masculinas conocidas en Edge y Windows. */
const MALE_NAMES = /\b(gonzalo|jorge|alvaro|álvaro|pablo|raul|raúl|tomas|tomás|emilio|gerardo|federico|alonso|lorenzo)\b/i;
const NEURAL_MARKERS = /natural|online|neural/i;

function regionOf(lang: string): string {
  return lang.toLowerCase().replace('_', '-').split('-')[1] ?? '';
}

function score(voice: VoiceInfo): number {
  let total = 0;
  // Una voz neuronal pesa más que el país: la diferencia de calidad se nota mucho.
  if (NEURAL_MARKERS.test(voice.name) || !voice.localService) total += 100;
  total += REGION_SCORES[regionOf(voice.lang)] ?? 5;
  if (MALE_NAMES.test(voice.name)) total += 8;
  return total;
}

/** La mejor voz en español disponible, o null si el navegador no tiene ninguna. */
export function pickSpanishVoice<T extends VoiceInfo>(voices: readonly T[]): T | null {
  const spanish = voices.filter((voice) => voice.lang.toLowerCase().startsWith('es'));
  if (spanish.length === 0) return null;
  return spanish.reduce((best, candidate) => (score(candidate) > score(best) ? candidate : best));
}
