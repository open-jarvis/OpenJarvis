import { useState, useCallback, useRef, useEffect } from 'react';
import { transcribeAudio, fetchSpeechHealth } from '../lib/api';

export type SpeechState = 'idle' | 'recording' | 'transcribing';

const MIN_RECORD_MS = 800;
const TIMESLICE_MS = 200;
const MIN_BLOB_BYTES = 500;
const RECORDER_BITRATE = 128_000;

function pickRecorderMimeType(): string | undefined {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ];
  for (const mime of candidates) {
    if (MediaRecorder.isTypeSupported(mime)) return mime;
  }
  return undefined;
}

function logStt(...args: unknown[]) {
  console.log('[STT]', ...args);
}

export function useSpeech() {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const startedAtRef = useRef(0);
  const mimeTypeRef = useRef('audio/webm');
  const audioCtxRef = useRef<AudioContext | null>(null);
  const levelRafRef = useRef<number | null>(null);
  const peakLevelRef = useRef(0);

  useEffect(() => {
    fetchSpeechHealth()
      .then((health) => setAvailable(health.available))
      .catch(() => setAvailable(false));
  }, []);

  // Tap the live mic stream with an AnalyserNode and track the loudest sample
  // seen while recording. This is the ground truth for "is the OS mic actually
  // producing signal" — independent of the Opus encoder or the backend.
  const startLevelMeter = useCallback((stream: MediaStream) => {
    try {
      const Ctx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new Ctx();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      peakLevelRef.current = 0;

      const sample = () => {
        analyser.getFloatTimeDomainData(buf);
        let peak = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = Math.abs(buf[i]);
          if (v > peak) peak = v;
        }
        if (peak > peakLevelRef.current) peakLevelRef.current = peak;
        levelRafRef.current = requestAnimationFrame(sample);
      };
      sample();
    } catch {
      // Web Audio unavailable — meter is best-effort, capture still proceeds.
    }
  }, []);

  const stopLevelMeter = useCallback(() => {
    if (levelRafRef.current != null) {
      cancelAnimationFrame(levelRafRef.current);
      levelRafRef.current = null;
    }
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  }, []);

  const cleanupStream = useCallback(() => {
    stopLevelMeter();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    mediaRecorderRef.current = null;
  }, [stopLevelMeter]);

  const startRecording = useCallback(async (): Promise<void> => {
    setError(null);

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Microphone not supported in this browser');
      return;
    }

    try {
      // noiseSuppression off: on Windows Edge it often strips quiet speech.
      // Detailed constraints can throw OverconstrainedError on some Edge mic
      // devices — fall back to a bare audio request so capture still starts.
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: false,
            autoGainControl: true,
          },
        });
      } catch (constraintErr) {
        if (
          constraintErr instanceof DOMException &&
          (constraintErr.name === 'OverconstrainedError' ||
            constraintErr.name === 'NotReadableError')
        ) {
          logStt('constraints rejected, retrying with audio:true', constraintErr.name);
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } else {
          throw constraintErr;
        }
      }
      streamRef.current = stream;

      const track = stream.getAudioTracks()[0];
      logStt('mic device', track?.label || '(unknown)', track?.getSettings?.());
      startLevelMeter(stream);

      const mimeType = pickRecorderMimeType();
      mimeTypeRef.current = mimeType ?? 'audio/webm';

      let recorder: MediaRecorder;
      try {
        recorder = new MediaRecorder(
          stream,
          mimeType
            ? { mimeType, audioBitsPerSecond: RECORDER_BITRATE }
            : { audioBitsPerSecond: RECORDER_BITRATE },
        );
      } catch {
        // Edge may reject explicit bitrate — fall back to mime-only/default.
        recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      }
      chunksRef.current = [];
      startedAtRef.current = Date.now();

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
          logStt('chunk', e.data.size, 'total', chunksRef.current.length);
        }
      };

      recorder.onerror = () => {
        setError('Recording failed — try again');
        setState('idle');
        cleanupStream();
      };

      recorder.start(TIMESLICE_MS);
      mediaRecorderRef.current = recorder;
      setState('recording');
      logStt('recording started', mimeTypeRef.current);
    } catch (err) {
      const denied =
        err instanceof DOMException &&
        (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
      setError(
        denied
          ? 'Microphone blocked — allow mic for localhost in Edge settings'
          : 'Could not access microphone',
      );
      setState('idle');
      cleanupStream();
    }
  }, [cleanupStream]);

  const stopRecording = useCallback(async (): Promise<string> => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === 'inactive') {
      throw new Error('Not recording');
    }

    const elapsed = Date.now() - startedAtRef.current;
    if (elapsed < MIN_RECORD_MS) {
      if (recorder.state === 'recording') {
        try {
          recorder.stop();
        } catch {
          /* track stop in cleanupStream handles Edge teardown */
        }
      }
      cleanupStream();
      setState('idle');
      const msg = 'Hold the mic longer — speak at least 1 second';
      setError(msg);
      return '';
    }

    return new Promise((resolve) => {
      recorder.onstop = async () => {
        setState('transcribing');
        const peak = peakLevelRef.current;
        cleanupStream();

        const blob = new Blob(chunksRef.current, {
          type: mimeTypeRef.current || 'audio/webm',
        });
        chunksRef.current = [];
        logStt(
          'blob bytes', blob.size,
          'type', blob.type,
          'ms', elapsed,
          'peakLevel', peak.toFixed(4),
        );

        try {
          // peak is the loudest raw sample (0..1) seen on the live mic stream.
          // Near-zero means the OS device itself produced no audio — no amount
          // of frontend/encoder tuning can recover signal that was never there.
          if (peak < 0.01) {
            setState('idle');
            const msg =
              `Mic is silent (input level ${peak.toFixed(3)}). Open Windows ` +
              'Sound settings → Input, pick the right microphone, raise its ' +
              'volume, and check it is not muted.';
            setError(msg);
            resolve('');
            return;
          }

          if (blob.size < MIN_BLOB_BYTES) {
            setState('idle');
            const msg =
              'Mic captured no audio — check Edge mic permission for localhost';
            setError(msg);
            resolve('');
            return;
          }

          const ext = blob.type.includes('mp4')
            ? 'recording.m4a'
            : blob.type.includes('ogg')
              ? 'recording.ogg'
              : 'recording.webm';
          const result = await transcribeAudio(blob, ext);
          setState('idle');
          const text = (result.text || '').trim();
          logStt('transcript', text || '(empty)');
          if (text) {
            setError(null);
          } else {
            setError(
              'No speech detected — speak clearly in English while holding the mic',
            );
          }
          resolve(text);
        } catch (err) {
          setState('idle');
          const msg =
            err instanceof Error ? err.message : 'Transcription failed';
          setError(msg);
          resolve('');
        }
      };

      // Calling stop() directly is the reliable path: the spec flushes the
      // final buffered chunk into one last `dataavailable` and then fires
      // `onstop`. The previous requestData()+setTimeout dance raced in Edge
      // and frequently dropped the tail of the recording.
      if (recorder.state !== 'inactive') {
        recorder.stop();
      }
    });
  }, [cleanupStream]);

  return {
    state,
    error,
    available,
    startRecording,
    stopRecording,
    isRecording: state === 'recording',
    isTranscribing: state === 'transcribing',
  };
}
