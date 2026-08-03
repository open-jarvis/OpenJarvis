import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSpeechHealth } from '../lib/api';
import { useJarvisStore } from '../lib/jarvisStore';
import {
  DisabledSpeechToTextProvider,
  LocalSpeechToTextProvider,
} from '../lib/speechProviders';
import type { SpeechToTextProvider } from '../lib/speechProviders';

export type SpeechState = 'idle' | 'recording' | 'transcribing';

const MAX_RECORDING_MS = 60_000;
const SILENCE_DURATION_MS = 900;
const SAMPLE_INTERVAL_MS = 50;
const NOISE_CALIBRATION_MS = 350;
const MIN_SPEECH_MS = 180;
const MIN_SPEECH_THRESHOLD = 0.012;

export function useSpeech(
  onAutoSubmit?: (transcript: string) => void,
  stopTts?: () => void,
) {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const [providerId, setProviderId] = useState('disabled');
  const [audioLevel, setAudioLevel] = useState(0);
  const stateRef = useRef<SpeechState>('idle');
  const providerRef = useRef<SpeechToTextProvider>(new DisabledSpeechToTextProvider());
  const limitTimerRef = useRef<number | null>(null);
  const sampleTimerRef = useRef<number | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const stopInFlightRef = useRef(false);
  const speechCandidateRef = useRef<number | null>(null);
  const speechDetectedRef = useRef(false);
  const silenceStartRef = useRef<number | null>(null);
  const calibrationStartedRef = useRef(0);
  const noiseSamplesRef = useRef<number[]>([]);
  const onAutoSubmitRef = useRef(onAutoSubmit);
  const stopTtsRef = useRef(stopTts);
  const setSpeech = useJarvisStore((store) => store.setSpeech);

  useEffect(() => { onAutoSubmitRef.current = onAutoSubmit; }, [onAutoSubmit]);
  useEffect(() => { stopTtsRef.current = stopTts; }, [stopTts]);

  const updateState = useCallback((next: SpeechState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const clearLimit = useCallback(() => {
    if (limitTimerRef.current !== null) window.clearTimeout(limitTimerRef.current);
    limitTimerRef.current = null;
  }, []);

  const stopSilenceDetection = useCallback(() => {
    if (sampleTimerRef.current !== null) window.clearInterval(sampleTimerRef.current);
    sampleTimerRef.current = null;
    analyserRef.current = null;
    if (audioCtxRef.current) {
      void audioCtxRef.current.close().catch(() => undefined);
      audioCtxRef.current = null;
    }
    speechCandidateRef.current = null;
    speechDetectedRef.current = false;
    silenceStartRef.current = null;
    noiseSamplesRef.current = [];
    setAudioLevel(0);
    setSpeech({ inputLevel: 0 });
  }, [setSpeech]);

  useEffect(() => {
    let active = true;
    const configure = async () => {
      let provider: SpeechToTextProvider = new DisabledSpeechToTextProvider();
      try {
        const health = await fetchSpeechHealth();
        if (health.stt_available && health.stt_location === 'local') {
          provider = new LocalSpeechToTextProvider(
            health.stt_provider || health.backend || 'local-stt',
            true,
          );
        }
      } catch {
        // STT intentionally remains disabled: recognition must stay local.
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
        lastError: provider.available ? null : 'Lokale Spracherkennung ist nicht verfügbar.',
      });
    };
    void configure();

    if (navigator.permissions?.query) {
      navigator.permissions.query({ name: 'microphone' as PermissionName })
        .then((permission) => {
          if (!active) return;
          setSpeech({ microphonePermission: permission.state });
          permission.onchange = () => setSpeech({ microphonePermission: permission.state });
        })
        .catch(() => setSpeech({ microphonePermission: 'unknown' }));
    }

    return () => {
      active = false;
      clearLimit();
      stopSilenceDetection();
      providerRef.current.dispose();
      setSpeech({ recording: false, inputLevel: 0 });
    };
  }, [clearLimit, setSpeech, stopSilenceDetection]);

  const finishRecording = useCallback(async (): Promise<string> => {
    if (stopInFlightRef.current) return '';
    stopInFlightRef.current = true;
    clearLimit();
    stopSilenceDetection();
    updateState('transcribing');
    setSpeech({ recording: false, inputLevel: 0 });
    try {
      const transcript = (await providerRef.current.stop()).trim();
      if (!transcript) throw new Error('Keine Sprache erkannt. Bitte erneut versuchen.');
      updateState('idle');
      return transcript;
    } catch (cause) {
      updateState('idle');
      const message = cause instanceof Error && cause.message
        ? cause.message
        : 'Lokale Transkription ist fehlgeschlagen.';
      setError(message);
      setSpeech({ lastError: message, recording: false, inputLevel: 0 });
      throw cause;
    } finally {
      stopInFlightRef.current = false;
    }
  }, [clearLimit, setSpeech, stopSilenceDetection, updateState]);

  const finishAndAutoSubmit = useCallback(async () => {
    try {
      const transcript = await finishRecording();
      if (transcript) onAutoSubmitRef.current?.(transcript);
    } catch {
      // finishRecording has already exposed a concrete, user-safe error.
    }
  }, [finishRecording]);

  const startDetector = useCallback((stream: MediaStream) => {
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    context.createMediaStreamSource(stream).connect(analyser);
    audioCtxRef.current = context;
    analyserRef.current = analyser;
    calibrationStartedRef.current = performance.now();
    noiseSamplesRef.current = [];
    speechDetectedRef.current = false;
    speechCandidateRef.current = null;
    silenceStartRef.current = null;
    const buffer = new Uint8Array(analyser.fftSize);

    sampleTimerRef.current = window.setInterval(() => {
      const activeAnalyser = analyserRef.current;
      if (!activeAnalyser || stateRef.current !== 'recording') return;
      activeAnalyser.getByteTimeDomainData(buffer);
      let sumSquares = 0;
      for (const value of buffer) {
        const normalized = (value - 128) / 128;
        sumSquares += normalized * normalized;
      }
      const rms = Math.sqrt(sumSquares / buffer.length);
      const level = Math.min(1, Math.max(0, rms * 6));
      setAudioLevel(level);
      setSpeech({ inputLevel: level });

      const now = performance.now();
      if (now - calibrationStartedRef.current < NOISE_CALIBRATION_MS) {
        noiseSamplesRef.current.push(rms);
        return;
      }
      const samples = noiseSamplesRef.current;
      const noiseFloor = samples.length
        ? samples.reduce((sum, sample) => sum + sample, 0) / samples.length
        : 0;
      const speechThreshold = Math.max(MIN_SPEECH_THRESHOLD, noiseFloor * 2.4 + 0.004);
      if (rms >= speechThreshold) {
        silenceStartRef.current = null;
        if (!speechDetectedRef.current) {
          speechCandidateRef.current ??= now;
          if (now - speechCandidateRef.current >= MIN_SPEECH_MS) {
            speechDetectedRef.current = true;
          }
        }
        return;
      }
      speechCandidateRef.current = null;
      if (!speechDetectedRef.current) return;
      silenceStartRef.current ??= now;
      if (now - silenceStartRef.current >= SILENCE_DURATION_MS) {
        void finishAndAutoSubmit();
      }
    }, SAMPLE_INTERVAL_MS);
  }, [finishAndAutoSubmit, setSpeech]);

  const startRecording = useCallback(async (): Promise<void> => {
    if (useJarvisStore.getState().speech.speaking) stopTtsRef.current?.();
    setError(null);
    stopInFlightRef.current = false;
    if (!providerRef.current.available) {
      const message = 'Lokale Spracherkennung ist nicht eingerichtet oder nicht erreichbar.';
      setError(message);
      setSpeech({ lastError: message, degraded: true });
      return;
    }
    try {
      await providerRef.current.start(useJarvisStore.getState().speech.language);
      updateState('recording');
      setSpeech({ recording: true, lastError: null });
      const provider = providerRef.current;
      if (provider instanceof LocalSpeechToTextProvider && provider.activeStream) {
        startDetector(provider.activeStream);
      }
      clearLimit();
      limitTimerRef.current = window.setTimeout(() => {
        setError('Aufnahme nach dem 60-Sekunden-Sicherheitslimit beendet.');
        void finishAndAutoSubmit();
      }, MAX_RECORDING_MS);
    } catch (cause) {
      const denied = cause instanceof DOMException && cause.name === 'NotAllowedError';
      const message = denied
        ? 'Mikrofonzugriff wurde verweigert. Bitte die Desktop-Berechtigung prüfen.'
        : cause instanceof Error && cause.message
          ? cause.message
          : 'Mikrofon konnte nicht gestartet werden.';
      setError(message);
      updateState('idle');
      setSpeech({
        recording: false,
        inputLevel: 0,
        lastError: message,
        microphonePermission: denied ? 'denied' : 'unknown',
      });
      providerRef.current.dispose();
    }
  }, [clearLimit, finishAndAutoSubmit, setSpeech, startDetector, updateState]);

  const stopRecording = useCallback(async (): Promise<string> => {
    if (stateRef.current !== 'recording') throw new Error('Das Mikrofon nimmt gerade nicht auf.');
    return finishRecording();
  }, [finishRecording]);

  const cancelRecording = useCallback(() => {
    clearLimit();
    stopSilenceDetection();
    stopInFlightRef.current = false;
    providerRef.current.dispose();
    updateState('idle');
    setError(null);
    setSpeech({ recording: false, inputLevel: 0 });
  }, [clearLimit, setSpeech, stopSilenceDetection, updateState]);

  return {
    state,
    error,
    available,
    providerId,
    audioLevel,
    startRecording,
    stopRecording,
    cancelRecording,
    isRecording: state === 'recording',
    isTranscribing: state === 'transcribing',
  };
}

export {
  MAX_RECORDING_MS,
  MIN_SPEECH_THRESHOLD as SILENCE_THRESHOLD,
  SILENCE_DURATION_MS,
};
