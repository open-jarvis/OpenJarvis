import { useEffect, useState } from 'react';

const CLAP_RMS_THRESHOLD = 0.2;
const CLAP_PEAK_RATIO = 2.5;

export function isClapPeak(previousRms: number, currentRms: number): boolean {
  return (
    currentRms >= CLAP_RMS_THRESHOLD &&
    currentRms >= previousRms * CLAP_PEAK_RATIO
  );
}

export function useClapWake(
  enabled: boolean,
  onClap: () => void,
): { listening: boolean; error: string | null } {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      setListening(false);
      setError(null);
      return;
    }

    let cancelled = false;
    let stream: MediaStream | null = null;
    let audioContext: AudioContext | null = null;
    let animationFrame = 0;
    let previousRms = 0;

    const release = () => {
      cancelAnimationFrame(animationFrame);
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      if (audioContext && audioContext.state !== 'closed') {
        void audioContext.close();
      }
      audioContext = null;
    };

    const listen = async () => {
      setError(null);
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
        setError('Clap wake is not supported in this browser.');
        return;
      }

      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          release();
          return;
        }

        audioContext = new AudioContext();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        audioContext.createMediaStreamSource(stream).connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        setListening(true);

        const checkLevel = () => {
          if (cancelled) return;
          analyser.getByteTimeDomainData(samples);
          let sumSquares = 0;
          for (const sample of samples) {
            const normalized = (sample - 128) / 128;
            sumSquares += normalized * normalized;
          }
          const rms = Math.sqrt(sumSquares / samples.length);
          if (isClapPeak(previousRms, rms)) {
            cancelled = true;
            release();
            setListening(false);
            onClap();
            return;
          }
          previousRms = rms;
          animationFrame = requestAnimationFrame(checkLevel);
        };

        animationFrame = requestAnimationFrame(checkLevel);
      } catch {
        if (!cancelled) {
          setError('Microphone access denied. Allow microphone access to use clap wake.');
        }
        release();
        setListening(false);
      }
    };

    void listen();
    return () => {
      cancelled = true;
      release();
      setListening(false);
    };
  }, [enabled, onClap]);

  return { listening, error };
}
