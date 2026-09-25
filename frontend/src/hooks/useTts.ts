import { useEffect } from 'react';
import { useTtsStore } from '../lib/tts';

export type { TtsState } from '../lib/tts';

/**
 * Read-aloud controls backed by the shared voice-output store.
 *
 * Every consumer talks to the same utterance, so starting one reply stops the
 * previous one instead of layering on top of it. The health probe runs once per
 * document, no matter how many components mount this hook.
 */
export function useTts() {
  const state = useTtsStore((s) => s.state);
  const speakingId = useTtsStore((s) => s.speakingId);
  const error = useTtsStore((s) => s.error);
  const available = useTtsStore((s) => s.available);
  const speak = useTtsStore((s) => s.speak);
  const stop = useTtsStore((s) => s.stop);
  const ensureHealth = useTtsStore((s) => s.ensureHealth);

  useEffect(() => {
    ensureHealth();
  }, [ensureHealth]);

  return {
    state,
    speakingId,
    error,
    available: available === true,
    speak,
    stop,
    isLoading: state === 'loading',
    isSpeaking: state === 'speaking',
  };
}
