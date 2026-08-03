import { useCallback, useEffect, useRef } from 'react';

/** One reusable Web-Audio chain for a very quiet processing bass. */
export function useProcessingTone(processing: boolean, enabled: boolean): () => void {
  const contextRef = useRef<AudioContext | null>(null);
  const oscillatorRef = useRef<OscillatorNode | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const stopNow = useCallback(() => {
    const context = contextRef.current;
    const gain = gainRef.current;
    if (!context || !gain) return;
    const now = context.currentTime;
    gain.gain.cancelScheduledValues(now);
    gain.gain.setTargetAtTime(0.0001, now, 0.03);
  }, []);

  useEffect(() => {
    if (!enabled || !processing) {
      const context = contextRef.current;
      const gain = gainRef.current;
      if (context && gain) {
        const now = context.currentTime;
        gain.gain.cancelScheduledValues(now);
        gain.gain.setTargetAtTime(0.0001, now, 0.09);
      }
      return;
    }

    try {
      let context = contextRef.current;
      if (!context) {
        context = new AudioContext();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = 54;
        gain.gain.value = 0.0001;
        oscillator.connect(gain).connect(context.destination);
        oscillator.start();
        contextRef.current = context;
        oscillatorRef.current = oscillator;
        gainRef.current = gain;
      }
      void context.resume().catch(() => undefined);
      const now = context.currentTime;
      gainRef.current?.gain.cancelScheduledValues(now);
      gainRef.current?.gain.setTargetAtTime(0.022, now, 0.16);
    } catch {
      // Visual processing remains fully functional without Web Audio.
    }
  }, [enabled, processing]);

  useEffect(() => () => {
    try { oscillatorRef.current?.stop(); } catch { /* already stopped */ }
    oscillatorRef.current = null;
    gainRef.current = null;
    void contextRef.current?.close().catch(() => undefined);
    contextRef.current = null;
  }, []);

  return stopNow;
}
