import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSpeechHealth } from '../lib/api';
import { useJarvisStore } from '../lib/jarvisStore';
import {
  BrowserSpeechToTextProvider,
  DisabledSpeechToTextProvider,
  LocalSpeechToTextProvider,
} from '../lib/speechProviders';
import type { SpeechToTextProvider } from '../lib/speechProviders';

export type SpeechState = 'idle' | 'recording' | 'transcribing';

const MAX_RECORDING_MS = 60_000;

export function useSpeech() {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const [providerId, setProviderId] = useState('disabled');
  const providerRef = useRef<SpeechToTextProvider>(new DisabledSpeechToTextProvider());
  const limitTimerRef = useRef<number | null>(null);
  const setSpeech = useJarvisStore((store) => store.setSpeech);

  const clearLimit = useCallback(() => {
    if (limitTimerRef.current !== null) window.clearTimeout(limitTimerRef.current);
    limitTimerRef.current = null;
  }, []);

  useEffect(() => {
    let active = true;
    const configure = async () => {
      let provider: SpeechToTextProvider = new DisabledSpeechToTextProvider();
      try {
        const health = await fetchSpeechHealth();
        if (health.stt_available && health.stt_location === 'local') {
          provider = new LocalSpeechToTextProvider(health.stt_provider || health.backend || 'local-stt', true);
        }
      } catch {
        // Browser capability below is the bounded fallback.
      }
      if (!provider.available) {
        const browser = new BrowserSpeechToTextProvider();
        if (browser.available) provider = browser;
      }
      if (!active) {
        provider.dispose();
        return;
      }
      providerRef.current.dispose();
      providerRef.current = provider;
      setAvailable(provider.available);
      setProviderId(provider.id);
      setSpeech({
        sttAvailable: provider.available,
        sttProvider: provider.location,
        degraded: !provider.available,
        lastError: provider.available ? null : 'Speech-to-text is unavailable.',
      });
    };
    void configure();

    if (navigator.permissions?.query) {
      navigator.permissions.query({ name: 'microphone' as PermissionName })
        .then((status) => {
          if (!active) return;
          setSpeech({ microphonePermission: status.state });
          status.onchange = () => setSpeech({ microphonePermission: status.state });
        })
        .catch(() => setSpeech({ microphonePermission: 'unknown' }));
    }

    return () => {
      active = false;
      clearLimit();
      providerRef.current.dispose();
      setSpeech({ recording: false });
    };
  }, [clearLimit, setSpeech]);

  const startRecording = useCallback(async (): Promise<void> => {
    setError(null);
    if (!providerRef.current.available) {
      const message = 'Speech-to-text is unavailable in this browser and no local provider is configured.';
      setError(message);
      setSpeech({ lastError: message, degraded: true });
      return;
    }
    try {
      const language = useJarvisStore.getState().speech.language;
      await providerRef.current.start(language);
      setState('recording');
      setSpeech({ recording: true, lastError: null });
      clearLimit();
      limitTimerRef.current = window.setTimeout(() => {
        const message = 'Recording stopped after the 60-second safety limit.';
        setError(message);
        setState('transcribing');
        setSpeech({ recording: false, lastError: message });
        void providerRef.current.stop()
          .catch(() => undefined)
          .finally(() => setState('idle'));
      }, MAX_RECORDING_MS);
    } catch (cause) {
      const message = cause instanceof Error && cause.message
        ? cause.message
        : 'Microphone access was denied.';
      setError(message);
      setState('idle');
      setSpeech({ recording: false, lastError: message, microphonePermission: 'denied' });
      providerRef.current.dispose();
    }
  }, [clearLimit, setSpeech]);

  const stopRecording = useCallback(async (): Promise<string> => {
    clearLimit();
    if (state !== 'recording') throw new Error('Microphone is not recording.');
    setState('transcribing');
    setSpeech({ recording: false });
    try {
      const transcript = await providerRef.current.stop();
      setState('idle');
      if (!transcript.trim()) throw new Error('No speech was recognized.');
      return transcript.trim();
    } catch (cause) {
      setState('idle');
      const message = cause instanceof Error ? cause.message : 'Transcription failed.';
      setError(message);
      setSpeech({ lastError: message, recording: false });
      throw cause;
    }
  }, [clearLimit, setSpeech, state]);

  const cancelRecording = useCallback((): void => {
    clearLimit();
    providerRef.current.dispose();
    setState('idle');
    setError(null);
    setSpeech({ recording: false });
  }, [clearLimit, setSpeech]);

  return {
    state,
    error,
    available,
    providerId,
    startRecording,
    stopRecording,
    cancelRecording,
    isRecording: state === 'recording',
    isTranscribing: state === 'transcribing',
  };
}

export { MAX_RECORDING_MS };
