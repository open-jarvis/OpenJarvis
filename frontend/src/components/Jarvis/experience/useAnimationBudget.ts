import { useEffect, useMemo, useState } from 'react';
import type { AnimationQuality } from './preferences';

export type AnimationFallbackTier = 1 | 2 | 3 | 4;

export function resolveAnimationTier(input: {
  quality: AnimationQuality;
  reducedMotion: boolean;
  pageVisible: boolean;
  fps: number | null;
}): AnimationFallbackTier {
  if (!input.pageVisible || input.quality === 'off') return 4;
  if (input.reducedMotion) return 4;
  if (input.quality === 'reduced') return 3;
  if (input.fps !== null && input.fps < 32) return 3;
  if (input.fps !== null && input.fps < 48) return 2;
  return 1;
}

export function useAnimationBudget(quality: AnimationQuality, reducedMotion: boolean) {
  const [pageVisible, setPageVisible] = useState(
    () => typeof document === 'undefined' || document.visibilityState === 'visible',
  );
  const [systemReducedMotion, setSystemReducedMotion] = useState(false);
  const [fps, setFps] = useState<number | null>(null);

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    const updateVisibility = () => setPageVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', updateVisibility);
    return () => document.removeEventListener('visibilitychange', updateVisibility);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setSystemReducedMotion(query.matches);
    update();
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined' || quality === 'off' || !pageVisible) {
      setFps(null);
      return undefined;
    }
    let frame = 0;
    let frameCount = 0;
    let sampleStarted = performance.now();
    const sample = (now: number) => {
      frameCount += 1;
      const elapsed = now - sampleStarted;
      if (elapsed >= 1_500) {
        setFps(Math.round((frameCount * 1_000) / elapsed));
        frameCount = 0;
        sampleStarted = now;
      }
      frame = window.requestAnimationFrame(sample);
    };
    frame = window.requestAnimationFrame(sample);
    return () => window.cancelAnimationFrame(frame);
  }, [pageVisible, quality]);

  const effectiveReducedMotion = reducedMotion || systemReducedMotion;
  const tier = useMemo(() => resolveAnimationTier({
    quality,
    reducedMotion: effectiveReducedMotion,
    pageVisible,
    fps,
  }), [effectiveReducedMotion, fps, pageVisible, quality]);

  return { tier, fps, pageVisible, reducedMotion: effectiveReducedMotion };
}
