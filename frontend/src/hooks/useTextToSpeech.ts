import { useCallback, useEffect, useRef, useState } from 'react';
import { useJarvisStore } from '../lib/jarvisStore';
import { fetchSpeechHealth } from '../lib/api';
import type { SpeechHealth } from '../lib/api';
import {
  DisabledTextToSpeechProvider,
  LOCAL_AUDIO_CHUNK_SKIPPED_EVENT,
  LOCAL_AUDIO_END_EVENT,
  LOCAL_AUDIO_FALLBACK_EVENT,
  LOCAL_AUDIO_LEVEL_EVENT,
  LOCAL_AUDIO_PROVIDER_EVENT,
  LOCAL_AUDIO_START_EVENT,
  LocalTextToSpeechProvider,
} from '../lib/speechProviders';
import type { TextToSpeechProvider } from '../lib/speechProviders';

export function useLocalAudioLevel(): number {
  const [level, setLevel] = useState(0);

  useEffect(() => {
    const reset = () => setLevel(0);
    const update = (event: Event) => {
      const next = (event as CustomEvent<{ level?: unknown }>).detail?.level;
      setLevel(typeof next === 'number' && Number.isFinite(next)
        ? Math.min(1, Math.max(0, next))
        : 0);
    };

    window.addEventListener(LOCAL_AUDIO_START_EVENT, reset);
    window.addEventListener(LOCAL_AUDIO_LEVEL_EVENT, update);
    window.addEventListener(LOCAL_AUDIO_END_EVENT, reset);
    return () => {
      window.removeEventListener(LOCAL_AUDIO_START_EVENT, reset);
      window.removeEventListener(LOCAL_AUDIO_LEVEL_EVENT, update);
      window.removeEventListener(LOCAL_AUDIO_END_EVENT, reset);
    };
  }, []);

  return level;
}

/** Reports which backend spoke and whether a fallback was used (visible indicator). */
export function useAudioBackendInfo(): {
  backend: string | null;
  fallbackUsed: boolean;
  cacheHit: boolean;
  chunksSkipped: number;
  lastError: string | null;
} {
  const [backend, setBackend] = useState<string | null>(null);
  const [fallbackUsed, setFallbackUsed] = useState(false);
  const [chunksSkipped, setChunksSkipped] = useState(0);
  const [cacheHit, setCacheHit] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  useEffect(() => {
    const onStart = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      setBackend(detail?.backend ?? null);
      setFallbackUsed(!!detail?.fallbackUsed);
      setCacheHit(!!detail?.cacheHit);
      setChunksSkipped(0);
      setLastError(null);
    };
    const onFallback = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      setFallbackUsed(true);
      setBackend(detail?.backend ?? null);
    };
    const onProvider = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      setBackend(detail?.backend ?? null);
      setFallbackUsed(!!detail?.fallbackUsed);
      setCacheHit(!!detail?.cacheHit);
    };
    const onSkipped = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.summary) setChunksSkipped(detail.skippedCount ?? 0);
      if (detail?.error) setLastError(String(detail.error));
    };
    const onEnd = () => {
      // Keep backend/fallback info visible until next speech starts.
    };
    window.addEventListener(LOCAL_AUDIO_START_EVENT, onStart);
    window.addEventListener(LOCAL_AUDIO_FALLBACK_EVENT, onFallback);
    window.addEventListener(LOCAL_AUDIO_PROVIDER_EVENT, onProvider);
    window.addEventListener(LOCAL_AUDIO_CHUNK_SKIPPED_EVENT, onSkipped);
    window.addEventListener(LOCAL_AUDIO_END_EVENT, onEnd);
    return () => {
      window.removeEventListener(LOCAL_AUDIO_START_EVENT, onStart);
      window.removeEventListener(LOCAL_AUDIO_FALLBACK_EVENT, onFallback);
      window.removeEventListener(LOCAL_AUDIO_PROVIDER_EVENT, onProvider);
      window.removeEventListener(LOCAL_AUDIO_CHUNK_SKIPPED_EVENT, onSkipped);
      window.removeEventListener(LOCAL_AUDIO_END_EVENT, onEnd);
    };
  }, []);

  return { backend, fallbackUsed, cacheHit, chunksSkipped, lastError };
}

export function useTextToSpeech() {
  const providerRef = useRef<TextToSpeechProvider>(new DisabledTextToSpeechProvider());
  const speaking = useJarvisStore((state) => state.speech.speaking);
  const language = useJarvisStore((state) => state.speech.language);
  const setSpeech = useJarvisStore((state) => state.setSpeech);
  const [providerInfo, setProviderInfo] = useState({ available: false, id: 'disabled' });

  useEffect(() => {
    let disposed = false;
    const configure = async () => {
      const health: SpeechHealth = await fetchSpeechHealth().catch(() => ({
        available: false,
        tts_available: false,
      }));
      if (disposed) return;
      providerRef.current = health.tts_available && health.tts_location === 'local'
        ? new LocalTextToSpeechProvider(health.tts_provider || 'local-tts', true)
        : new DisabledTextToSpeechProvider();
      setProviderInfo({ available: providerRef.current.available, id: providerRef.current.id });
      setSpeech({
        ttsAvailable: providerRef.current.available,
        ttsProvider: providerRef.current.location,
        degraded: !providerRef.current.available && !useJarvisStore.getState().speech.sttAvailable,
      });
    };
    void configure();
    return () => {
      disposed = true;
      providerRef.current.stop();
      setSpeech({ speaking: false });
    };
  }, [setSpeech]);

  const stop = useCallback(() => {
    providerRef.current.stop();
    setSpeech({ speaking: false });
  }, [setSpeech]);

  const speak = useCallback((text: string) => {
    if (!text.trim()) return;
    providerRef.current.speak(
      text,
      language,
      () => setSpeech({ speaking: false }),
      (message) => setSpeech({ speaking: false, lastError: message }),
    );
    if (providerRef.current.available) {
      setSpeech({ speaking: true, lastError: null });
    }
  }, [language, setSpeech]);

  return {
    available: providerInfo.available,
    providerId: providerInfo.id,
    speaking,
    language,
    speak,
    stop,
  };
}
