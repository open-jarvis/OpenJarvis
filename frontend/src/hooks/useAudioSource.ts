import { useCallback, useEffect, useRef, useState } from 'react';

export type AudioInputMode = 'sim' | 'mic';

export interface UseAudioSourceResult {
  mode: AudioInputMode;
  setMode: (m: AudioInputMode) => Promise<void>;
  getFrequencyData: () => Float32Array | Uint8Array;
  micError: string | null;
  clearMicError: () => void;
  isFileProtocol: boolean;
}

export function useAudioSource(speed: number): UseAudioSourceResult {
  const [mode, setModeState] = useState<AudioInputMode>('sim');
  const [micError, setMicError] = useState<string | null>(null);

  const isFileProtocol = typeof window !== 'undefined' && window.location.protocol === 'file:';

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const dataRef = useRef<Uint8Array>(new Uint8Array(0));
  const speedRef = useRef(speed);
  const simRef = useRef({ t: 0, vol: 0.12, freqs: new Float32Array(128) });

  useEffect(() => { speedRef.current = speed; }, [speed]);

  const stepMock = useCallback((): Float32Array => {
    const sim = simRef.current;
    sim.t += 0.028 * speedRef.current;
    const talking = Math.sin(sim.t * 0.12) > -0.3;
    const target = talking
      ? 0.15
        + 0.16 * Math.abs(Math.sin(sim.t * 2.1)) * Math.sin(sim.t * 0.9)
        + 0.05 * Math.cos(sim.t * 14) * Math.sin(sim.t * 5.5)
      : 0.06;
    sim.vol += (target - sim.vol) * 0.14;
    for (let i = 0; i < sim.freqs.length; i++) {
      const base = Math.exp(-i * 0.048) * 175;
      const mod = Math.sin(sim.t * (1.4 + i * 0.09)) * 45 * sim.vol;
      const jit = i > 35 ? Math.sin(sim.t * (11 + i)) * 10 * sim.vol : 0;
      sim.freqs[i] = Math.max(0, base * (sim.vol * 1.6) + mod + jit);
    }
    return sim.freqs;
  }, []);

  const getFrequencyData = useCallback((): Float32Array | Uint8Array => {
    if (mode === 'mic' && analyserRef.current) {
      analyserRef.current.getByteFrequencyData(dataRef.current);
      return dataRef.current;
    }
    return stepMock();
  }, [mode, stepMock]);

  const stopMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    const ac = audioCtxRef.current;
    if (ac && ac.state !== 'closed') void ac.close();
    audioCtxRef.current = null;
    analyserRef.current = null;
  }, []);

  const setMode = useCallback(
    async (m: AudioInputMode): Promise<void> => {
      if (m === 'mic') {
        if (isFileProtocol || !navigator.mediaDevices?.getUserMedia) {
          setMicError(
            isFileProtocol
              ? 'Mic requires localhost. Run: python3 -m http.server 8080'
              : 'Browser does not support mic (requires HTTPS or localhost)',
          );
          return;
        }
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
          const ac = new AudioContext();
          const analyser = ac.createAnalyser();
          analyser.fftSize = 256;
          ac.createMediaStreamSource(stream).connect(analyser);
          audioCtxRef.current = ac;
          analyserRef.current = analyser;
          dataRef.current = new Uint8Array(analyser.frequencyBinCount);
          streamRef.current = stream;
          setMicError(null);
          setModeState('mic');
        } catch (e) {
          const name = e instanceof Error ? e.name : '';
          const isBlocked = name === 'NotAllowedError' || name === 'PermissionDeniedError';
          setMicError(
            isBlocked
              ? 'permission_denied'
              : `Mic error: ${e instanceof Error ? e.message : String(e)}`,
          );
        }
      } else {
        stopMic();
        setModeState('sim');
      }
    },
    [isFileProtocol, stopMic],
  );

  useEffect(() => () => stopMic(), [stopMic]);

  return {
    mode,
    setMode,
    getFrequencyData,
    micError,
    clearMicError: () => setMicError(null),
    isFileProtocol,
  };
}
