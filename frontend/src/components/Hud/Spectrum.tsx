import { useEffect, useRef, type MutableRefObject } from 'react';
import type { HudMode } from './CoreReactor';

/**
 * Mirrored frequency bars + oscilloscope line. Uses the live microphone
 * analyser while listening, otherwise synthesises a signal from the
 * current activity level so the panel always reflects what Jarvis is doing.
 */
export function Spectrum({
  analyserRef,
  levelRef,
  mode,
}: {
  analyserRef: MutableRefObject<AnalyserNode | null>;
  levelRef: MutableRefObject<number>;
  mode: HudMode;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext('2d')!;
    const BARS = 40;
    const smooth = new Float32Array(BARS);
    let freq = new Uint8Array(0);
    let raf = 0;

    const draw = (t: number) => {
      const w = canvas.clientWidth, h = canvas.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const an = analyserRef.current;
      if (an && freq.length !== an.frequencyBinCount) freq = new Uint8Array(an.frequencyBinCount);
      if (an) an.getByteFrequencyData(freq);
      const lvl = levelRef.current;
      const m = modeRef.current;

      for (let i = 0; i < BARS; i++) {
        let v: number;
        if (an && freq.length) {
          v = freq[Math.floor((i / BARS) * freq.length * 0.7)] / 255;
        } else {
          const base = m === 'idle' || m === 'offline' ? 0.04 : lvl;
          v = base * (0.4 + 0.6 * Math.abs(Math.sin(t / 180 + i * 0.55) * Math.cos(t / 410 + i * 0.21)));
        }
        smooth[i] += (v - smooth[i]) * 0.25;
      }

      // grid
      ctx.strokeStyle = 'rgba(0,229,255,0.08)';
      ctx.lineWidth = 1;
      for (let y = 0; y <= h; y += h / 4) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }

      const bw = w / BARS;
      const mid = h / 2;
      for (let i = 0; i < BARS; i++) {
        const bh = Math.max(1, smooth[i] * (h * 0.48));
        const g = ctx.createLinearGradient(0, mid - bh, 0, mid + bh);
        g.addColorStop(0, 'rgba(0,229,255,0.15)');
        g.addColorStop(0.5, 'rgba(120,255,240,0.95)');
        g.addColorStop(1, 'rgba(0,229,255,0.15)');
        ctx.fillStyle = g;
        ctx.fillRect(i * bw + 1, mid - bh, bw - 2, bh * 2);
      }

      // oscilloscope
      ctx.strokeStyle = 'rgba(180,255,255,0.7)';
      ctx.beginPath();
      for (let x = 0; x <= w; x += 3) {
        const amp = (lvl + 0.05) * h * 0.25;
        const y = mid + Math.sin(x / 14 + t / 120) * amp * Math.sin(x / w * Math.PI);
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [analyserRef, levelRef]);

  return <canvas ref={canvasRef} className="hud-spectrum" aria-hidden="true" />;
}
