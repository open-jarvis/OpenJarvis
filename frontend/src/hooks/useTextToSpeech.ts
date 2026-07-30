import { useCallback, useEffect, useRef } from 'react';
import { useJarvisStore } from '../lib/jarvisStore';
import {
  BrowserTextToSpeechProvider,
  DisabledTextToSpeechProvider,
} from '../lib/speechProviders';
import type { TextToSpeechProvider } from '../lib/speechProviders';

export function useTextToSpeech() {
  const providerRef = useRef<TextToSpeechProvider>(new DisabledTextToSpeechProvider());
  const speaking = useJarvisStore((state) => state.speech.speaking);
  const language = useJarvisStore((state) => state.speech.language);
  const setSpeech = useJarvisStore((state) => state.setSpeech);

  useEffect(() => {
    const browser = new BrowserTextToSpeechProvider();
    providerRef.current = browser.available ? browser : new DisabledTextToSpeechProvider();
    setSpeech({
      ttsAvailable: providerRef.current.available,
      ttsProvider: providerRef.current.location,
      degraded: !providerRef.current.available && !useJarvisStore.getState().speech.sttAvailable,
    });
    return () => {
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
    available: providerRef.current.available,
    providerId: providerRef.current.id,
    speaking,
    language,
    speak,
    stop,
  };
}
