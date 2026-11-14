import { useEffect, useRef, type MutableRefObject } from 'react';

export type HudMode = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'offline';

const MODE_LABEL: Record<HudMode, string> = {
  idle: 'STANDBY',
  listening: 'LISTENING',
  transcribing: 'DECODING',
  thinking: 'PROCESSING',
  speaking: 'RESPONDING',
  offline: 'OFFLINE',
};

const MODE_HINT: Record<HudMode, string> = {
  idle: 'TAP CORE TO SPEAK',
  listening: 'TAP TO STOP',
  transcribing: 'PLEASE WAIT',
  thinking: 'TAP TO ABORT',
  speaking: 'TAP TO SILENCE',
  offline: 'BACKEND UNREACHABLE',
};

/**
 * The central reactor: SVG ring stack plus a canvas point-sphere that
 * breathes with the microphone / speech level. Tapping it is the main
 * action (start/stop voice, abort, silence).
 */
export function CoreReactor({
  mode,
  levelRef,
  onActivate,
}: {
  mode: HudMode;
  levelRef: MutableRefObject<number>;
  onActivate: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext('2d')!;
    const N = 420;
    const pts = Array.from({ length: N }, (_, i) => {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const t = i * Math.PI * (3 - Math.sqrt(5));
      return [Math.cos(t) * r, y, Math.sin(t) * r];
    });
    let raf = 0;
    let rot = 0;
    let smooth = 0;
    let last = performance.now();

    const draw = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      const size = canvas.clientWidth;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (canvas.width !== size * dpr) {
        canvas.width = size * dpr;
        canvas.height = size * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);

      const m = modeRef.current;
      let target = levelRef.current;
      if (m === 'thinking') target = 0.35 + Math.sin(now / 160) * 0.15;
      if (m === 'transcribing') target = 0.25 + Math.sin(now / 90) * 0.1;
      if (m === 'idle' || m === 'offline') target = 0.05 + Math.sin(now / 900) * 0.04;
      smooth += (target - smooth) * Math.min(dt * 10, 1);

      const spin = m === 'thinking' ? 1.6 : m === 'speaking' || m === 'listening' ? 0.9 : 0.35;
      rot += dt * spin;
      const c = size / 2;
      const R = size * 0.3 * (1 + smooth * 0.35);
      const hue = m === 'offline' ? '255,80,80' : m === 'listening' ? '120,255,200' : '0,229,255';

      // Inner glow
      const g = ctx.createRadialGradient(c, c, 0, c, c, R * 1.4);
      g.addColorStop(0, `rgba(${hue},${0.35 + smooth * 0.4})`);
      g.addColorStop(0.5, `rgba(${hue},0.08)`);
      g.addColorStop(1, `rgba(${hue},0)`);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, size, size);

      const cy = Math.cos(rot), sy = Math.sin(rot);
      const tilt = 0.35, ct = Math.cos(tilt), st = Math.sin(tilt);
      for (let i = 0; i < N; i++) {
        const [x, y, z] = pts[i];
        const wobble = 1 + Math.sin(i * 1.7 + now / 220) * smooth * 0.18;
        const x1 = x * cy + z * sy;
        const z1 = -x * sy + z * cy;
        const y2 = y * ct - z1 * st;
        const z2 = y * st + z1 * ct;
        const persp = 1 / (1.8 - z2 * 0.6);
        const px = c + x1 * R * wobble * persp * 1.3;
        const py = c + y2 * R * wobble * persp * 1.3;
        const a = 0.15 + (z2 + 1) * 0.4;
        ctx.fillStyle = `rgba(${hue},${a})`;
        const s = 0.6 + (z2 + 1) * 0.9;
        ctx.fillRect(px - s / 2, py - s / 2, s, s);
      }

      // Equator ring
      ctx.strokeStyle = `rgba(${hue},0.5)`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.ellipse(c, c, R * 0.95, R * 0.95 * Math.abs(st) + 2, 0, 0, Math.PI * 2);
      ctx.stroke();

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [levelRef]);

  const ticks = Array.from({ length: 120 }, (_, i) => i);
  const segs = Array.from({ length: 36 }, (_, i) => i);

  return (
    <button
      type="button"
      className={`hud-core hud-core--${mode}`}
      onClick={onActivate}
      aria-label={`Jarvis core: ${MODE_LABEL[mode]}. ${MODE_HINT[mode]}`}
    >
      <svg viewBox="0 0 600 600" className="hud-core__svg" aria-hidden="true">
        <defs>
          <filter id="hudGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Outer tick ring */}
        <g className="ring ring--ticks">
          {ticks.map((i) => (
            <line
              key={i}
              x1="300" y1="14" x2="300" y2={i % 10 === 0 ? 34 : i % 5 === 0 ? 28 : 22}
              transform={`rotate(${i * 3} 300 300)`}
              className={i % 10 === 0 ? 'tick tick--major' : 'tick'}
            />
          ))}
        </g>

        {/* Segmented energy ring */}
        <g className="ring ring--segs" filter="url(#hudGlow)">
          {segs.map((i) => (
            <path
              key={i}
              d="M 300 52 A 248 248 0 0 1 340 55"
              transform={`rotate(${i * 10} 300 300)`}
              className={`seg seg--${i % 4}`}
            />
          ))}
        </g>

        {/* Dashed mid ring */}
        <circle cx="300" cy="300" r="222" className="ring ring--dash" />

        {/* Bracket arcs */}
        <g className="ring ring--brackets" filter="url(#hudGlow)">
          <path d="M 120 300 A 180 180 0 0 1 210 144" />
          <path d="M 480 300 A 180 180 0 0 1 390 456" />
          <path d="M 390 144 A 180 180 0 0 1 456 210" />
          <path d="M 210 456 A 180 180 0 0 1 144 390" />
        </g>

        {/* Hex pods */}
        <g className="pods">
          {[0, 90, 180, 270].map((deg) => (
            <g key={deg} transform={`rotate(${deg} 300 300)`}>
              <polygon
                points="300,58 318,68 318,88 300,98 282,88 282,68"
                className="pod"
              />
              <circle cx="300" cy="78" r="4" className="pod-dot" />
            </g>
          ))}
        </g>

        {/* Inner scanning ring */}
        <g className="ring ring--scan">
          <circle cx="300" cy="300" r="160" className="scan-track" />
          <path d="M 300 140 A 160 160 0 0 1 460 300" className="scan-arc" filter="url(#hudGlow)" />
        </g>
      </svg>

      <canvas ref={canvasRef} className="hud-core__sphere" aria-hidden="true" />

      <span className="hud-core__label">
        <span className="hud-core__mode">{MODE_LABEL[mode]}</span>
        <span className="hud-core__hint">{MODE_HINT[mode]}</span>
      </span>
    </button>
  );
}
