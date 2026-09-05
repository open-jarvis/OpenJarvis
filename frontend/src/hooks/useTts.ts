import { useState, useCallback, useRef, useEffect } from 'react';
import { synthesizeSpeech, fetchTtsHealth } from '../lib/api';

export type TtsState = 'idle' | 'loading' | 'speaking';

/**
 * Play assistant replies through the server's TTS backend.
 *
 * One utterance plays at a time: starting a new one stops whatever is running,
 * and a stale request that resolves after the user moved on is discarded rather
 * than played over the top.
 */
export function useTts() {
  const [state, setState] = useState<TtsState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const requestRef = useRef(0);

  useEffect(() => {
    fetchTtsHealth()
      .then((health) => setAvailable(health.available))
      .catch(() => setAvailable(false));
  }, []);

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    requestRef.current += 1;
    cleanup();
    setState('idle');
  }, [cleanup]);

  const speak = useCallback(
    async (text: string): Promise<void> => {
      const trimmed = text.trim();
      if (!trimmed) return;

      requestRef.current += 1;
      const token = requestRef.current;
      cleanup();
      setError(null);
      setState('loading');

      try {
        const blob = await synthesizeSpeech(trimmed);
        if (token !== requestRef.current) return; // superseded while synthesizing

        const url = URL.createObjectURL(blob);
        urlRef.current = url;

        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = () => {
          if (token === requestRef.current) {
            cleanup();
            setState('idle');
          }
        };
        audio.onerror = () => {
          if (token === requestRef.current) {
            cleanup();
            setError('Playback failed');
            setState('idle');
          }
        };

        await audio.play();
        if (token === requestRef.current) setState('speaking');
      } catch (err) {
        if (token !== requestRef.current) return;
        cleanup();
        setError(err instanceof Error ? err.message : 'Speech synthesis failed');
        setState('idle');
      }
    },
    [cleanup],
  );

  // Never leave audio playing or a blob URL leaked behind an unmounted view.
  useEffect(() => cleanup, [cleanup]);

  return {
    state,
    error,
    available,
    speak,
    stop,
    isLoading: state === 'loading',
    isSpeaking: state === 'speaking',
  };
}
