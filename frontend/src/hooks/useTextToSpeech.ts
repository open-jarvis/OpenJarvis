import { useCallback, useEffect, useRef, useState } from 'react';
import { useJarvisStore } from '../lib/jarvisStore';
import { fetchSpeechHealth } from '../lib/api';
import type { SpeechHealth } from '../lib/api';
import {
  BrowserTextToSpeechProvider,
  DisabledTextToSpeechProvider,
  LOCAL_AUDIO_END_EVENT,
  LOCAL_AUDIO_LEVEL_EVENT,
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

export function useTextToSpeech() {
  const providerRef = useRef<TextToSpeechProvider>(new DisabledTextToSpeechProvider());
  const speaking = useJarvisStore((state) => state.speech.speaking);
  const language = useJarvisStore((state) => state.speech.language);
  const setSpeech = useJarvisStore((state) => state.setSpeech);
  const [providerInfo, setProviderInfo] = useState({ available: false, id: 'disabled' });

  useEffect(() => {
    let disposed = false;
    const browser = new BrowserTextToSpeechProvider();
    const configure = async () => {
      const health: SpeechHealth = await fetchSpeechHealth().catch(() => ({
        available: false,
        tts_available: false,
      }));
      if (disposed) return;
      providerRef.current = health.tts_available && health.tts_location === 'local'
        ? new LocalTextToSpeechProvider(health.tts_provider || 'local-tts', true, browser)
        : browser.available ? browser : new DisabledTextToSpeechProvider();
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
