import { useState, useCallback, useRef, useEffect } from 'react';
import { transcribeAudio, fetchSpeechHealth } from '../lib/api';

export type SpeechState = 'idle' | 'recording' | 'transcribing';

interface SpeechRecordingOptions {
  /** Automatically stop after a spoken phrase, then deliver its transcript. */
  autoStopOnSilence?: boolean;
  onTranscript?: (text: string) => void;
}

const VOICE_ACTIVITY_THRESHOLD = 0.018;
const END_OF_SPEECH_MS = 1_200;
const STARTUP_SILENCE_MS = 10_000;

export function useSpeech() {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const transcriptCallbackRef = useRef<((text: string) => void) | null>(null);

  const stopMetering = useCallback(() => {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context && context.state !== 'closed') void context.close();
  }, []);

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const health = await fetchSpeechHealth();
      setAvailable(health.available);
    } catch {
      // The local API may be starting while the frontend is already open.
      // Keep the microphone disabled and retry on the next health check.
      setAvailable(false);
    }
  }, []);

  // The server may restart or gain its local speech model after the frontend
  // is open. Recheck periodically and whenever the user returns to the tab,
  // rather than leaving a stale "not configured" status indefinitely.
  useEffect(() => {
    void refreshHealth();

    const onFocus = () => void refreshHealth();
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refreshHealth();
    };
    const interval = window.setInterval(() => void refreshHealth(), 15_000);

    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [refreshHealth]);

  // Do not leave a browser microphone track active if the chat is unmounted
  // during recording (for example, when navigating to another page).
  useEffect(() => () => {
    stopMetering();
    transcriptCallbackRef.current = null;
    const recorder = mediaRecorderRef.current;
    if (recorder?.state === 'recording') {
      recorder.onstop = null;
      recorder.stop();
    }
    stopTracks();
  }, [stopMetering, stopTracks]);

  const stopRecording = useCallback(async (): Promise<string> => {
    return new Promise((resolve, reject) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state !== 'recording') {
        reject(new Error('Not recording'));
        return;
      }

      stopMetering();
      const onTranscript = transcriptCallbackRef.current;
      transcriptCallbackRef.current = null;

      recorder.onstop = async () => {
        mediaRecorderRef.current = null;
        setState('transcribing');
        stopTracks();

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        chunksRef.current = [];

        try {
          const result = await transcribeAudio(blob);
          setState('idle');
          onTranscript?.(result.text);
          resolve(result.text);
        } catch (err) {
          setState('idle');
          const msg = err instanceof Error ? err.message : 'Transcription failed';
          setError(msg);
          reject(err);
        }
      };

      recorder.stop();
    });
  }, [stopMetering, stopTracks]);

  const startRecording = useCallback(async (options: SpeechRecordingOptions = {}): Promise<void> => {
    setError(null);

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Microphone not supported in this browser');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      transcriptCallbackRef.current = options.onTranscript ?? null;
      setState('recording');

      if (options.autoStopOnSilence) {
        const audioContext = new AudioContext();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 1024;
        audioContext.createMediaStreamSource(stream).connect(analyser);
        audioContextRef.current = audioContext;

        const samples = new Uint8Array(analyser.fftSize);
        const startedAt = performance.now();
        let lastSpeechAt = startedAt;
        let heardSpeech = false;

        const measure = () => {
          if (mediaRecorderRef.current !== recorder || recorder.state !== 'recording') return;

          analyser.getByteTimeDomainData(samples);
          let energy = 0;
          for (const sample of samples) {
            const centered = (sample - 128) / 128;
            energy += centered * centered;
          }
          const rms = Math.sqrt(energy / samples.length);
          const now = performance.now();
          if (rms >= VOICE_ACTIVITY_THRESHOLD) {
            heardSpeech = true;
            lastSpeechAt = now;
          }

          if (!heardSpeech && now - startedAt >= STARTUP_SILENCE_MS) {
            // No speech was detected. Discard the local buffer instead of
            // uploading a silence clip to the transcription endpoint.
            transcriptCallbackRef.current = null;
            stopMetering();
            mediaRecorderRef.current = null;
            recorder.onstop = null;
            recorder.stop();
            chunksRef.current = [];
            stopTracks();
            setState('idle');
            return;
          }
          if (heardSpeech && now - lastSpeechAt >= END_OF_SPEECH_MS) {
            void stopRecording().catch(() => {});
            return;
          }
          animationFrameRef.current = window.requestAnimationFrame(measure);
        };
        animationFrameRef.current = window.requestAnimationFrame(measure);
      }
    } catch (err) {
      setError('Microphone access denied');
      setState('idle');
    }
  }, [stopRecording]);

  const cancelRecording = useCallback(() => {
    transcriptCallbackRef.current = null;
    stopMetering();
    const recorder = mediaRecorderRef.current;
    mediaRecorderRef.current = null;
    if (recorder?.state === 'recording') {
      recorder.onstop = null;
      recorder.stop();
    }
    chunksRef.current = [];
    stopTracks();
    setState('idle');
  }, [stopMetering, stopTracks]);

  return {
    state,
    error,
    available,
    startRecording,
    stopRecording,
    cancelRecording,
    isRecording: state === 'recording',
    isTranscribing: state === 'transcribing',
  };
}
