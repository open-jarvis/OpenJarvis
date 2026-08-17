import { useEffect, useRef } from 'react';
import type { VisualizerSettings } from './types';

// ── Fibonacci sphere points — computed once at module level ──────────────────
// Denser cloud reads as a cohesive liquid surface rather than scattered dots.
const N = 1200;
const SPHERE_PTS = Array.from({ length: N }, (_, i) => {
  const phi = Math.acos(-1 + (2 * i) / N);
  const theta = Math.sqrt(N * Math.PI) * phi;
  return {
    theta,
    phi,
    u: Math.cos(theta) * Math.sin(phi),
    v: Math.sin(theta) * Math.sin(phi),
    w: Math.cos(phi),
  };
});

type Pal = readonly [string, string, string]; // [colorA, colorB, glow]
export const PALETTES: Record<string, Pal> = {
  gold:   ['#ffd700', '#ff9500', 'rgba(255,190,0,0.9)'],
  cyan:   ['#00f2fe', '#4facfe', 'rgba(0,242,254,0.85)'],
  cyber:  ['#ff007f', '#7f00ff', 'rgba(255,0,127,0.85)'],
  aurora: ['#00ff87', '#60efff', 'rgba(0,255,135,0.85)'],
  sunset: ['#ff0844', '#ffb199', 'rgba(255,8,68,0.85)'],
};

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function blendHex(a: string, b: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  return `rgb(${Math.round(r1 + (r2 - r1) * t)},${Math.round(g1 + (g2 - g1) * t)},${Math.round(b1 + (b2 - b1) * t)})`;
}

interface RS { rotAngle: number; pulse: number; rotX: number; rotY: number }

function renderWaveRing(
  ctx: CanvasRenderingContext2D,
  cx: number, cy: number,
  avgVol: number, bassVol: number, ad: Float32Array | Uint8Array,
  s: VisualizerSettings, rs: RS,
) {
  const pal = PALETTES[s.theme] ?? PALETTES['gold']!;
  const base = s.size + bassVol * 50;
  for (let l = 0; l < 3; l++) {
    const phase = l * Math.PI * 0.33;
    const grad = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, base * 1.6);
    if (l === 0)      { grad.addColorStop(0, pal[0]); grad.addColorStop(1, pal[1]); }
    else if (l === 1) { grad.addColorStop(0, pal[1]); grad.addColorStop(1, '#8800ff'); }
    else              { grad.addColorStop(0, pal[0] + 'aa'); grad.addColorStop(1, 'rgba(255,255,255,.3)'); }
    ctx.save();
    ctx.strokeStyle = grad;
    ctx.lineWidth = 2.8 - l * 0.7;
    ctx.globalAlpha = 0.9 - l * 0.25;
    if (s.glow > 0 && l === 0) { ctx.shadowBlur = s.glow; ctx.shadowColor = pal[2]; }
    ctx.beginPath();
    for (let i = 0; i <= 200; i++) {
      const ang = (i / 200) * Math.PI * 2;
      const bi = Math.floor(
        (Math.abs(Math.sin(ang)) * 0.65 + Math.abs(Math.cos(ang)) * 0.35) * (ad.length - 1) * 0.55,
      );
      const amp = ((ad[bi] ?? 0) / 255) * 58 * s.gain;
      const rip = Math.sin(ang * 7 + rs.pulse * 1.4 + phase) * Math.cos(ang * 3 - rs.pulse * 0.75) * 7;
      const ar = amp * Math.sin(ang * 11 + rs.pulse * 1.9 + phase);
      const r = base + rip + ar;
      const a = ang + rs.rotAngle * (1 - l * 0.14);
      if (i === 0) ctx.moveTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
      else          ctx.lineTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
    }
    ctx.closePath(); ctx.stroke(); ctx.restore();
  }
}

function renderSphere(
  ctx: CanvasRenderingContext2D,
  cx: number, cy: number,
  avgVol: number, bassVol: number, ad: Float32Array | Uint8Array,
  s: VisualizerSettings, rs: RS, isDragging: boolean,
) {
  const pal = PALETTES[s.theme] ?? PALETTES['gold']!;
  // Overall sound energy drives how violently the liquid morphs — but the whole
  // surface moves together (coherent), it does not balloon outward per band.
  const energy = Math.min(1.4, bassVol * 0.7 + avgVol * 0.6);
  // Gentle size breathing only (much smaller than before → no "ballooning").
  const base = s.size - 6 + bassVol * 12;
  if (!isDragging) { rs.rotY += 0.0024 * s.speed; rs.rotX += 0.001 * s.speed; }
  const cosY = Math.cos(rs.rotY), sinY = Math.sin(rs.rotY);
  const cosX = Math.cos(rs.rotX), sinX = Math.sin(rs.rotX);

  // Surface displacement amplitude: a small idle wobble + audio-driven swell.
  const morph = (0.10 + energy * 0.38) * s.gain;
  const t = rs.pulse * 0.5; // advect the field over time → it keeps flowing

  const proj = SPHERE_PTS.map((pt) => {
    // Smooth, time-advected flow field over the sphere surface. Summing a few
    // LOW-frequency sines of the 3D position makes the displacement vary
    // *continuously* between neighbouring points — so the cloud deforms like a
    // connected blob of liquid instead of dots jumping per frequency band.
    const f =
      Math.sin(pt.u * 3.1 + t) +
      Math.sin(pt.v * 3.3 - t * 1.2) +
      Math.sin(pt.w * 2.7 + t * 0.8) +
      Math.sin((pt.u + pt.w) * 2.2 + t * 1.4) +
      Math.sin((pt.v - pt.u) * 2.6 - t * 0.9);
    // f/5 ∈ ~[-1,1]; clamp so the surface undulates strongly yet never collapses
    // through the centre or explodes — it stays a recognizable morphing blob.
    const disp = Math.max(-0.5, Math.min(0.7, morph * (f / 5)));
    const r = base * (1 + disp);
    const x3 = pt.u * r, y3 = pt.v * r, z3 = pt.w * r;
    const x1 = x3 * cosY - z3 * sinY;
    const z1 = x3 * sinY + z3 * cosY;
    const y2 = y3 * cosX - z1 * sinX;
    const z2 = y3 * sinX + z1 * cosX;
    return { x2: x1, y2, z2 }; // x2: x1 — avoids undefined-variable bug from plain x2
  });

  proj.sort((a, b) => b.z2 - a.z2);
  const CAM = 360;
  for (const p of proj) {
    const sc = CAM / (CAM + p.z2);
    const sx = cx + p.x2 * sc;
    const sy = cy + p.y2 * sc;
    const zn = (p.z2 + base) / (base * 2);
    // Smaller, more uniform dots → the surface reads as one liquid mass.
    const sz = Math.max(0.6, (0.8 + zn * 1.7) * sc);
    ctx.globalAlpha = Math.max(0.06, 0.12 + zn * 0.8);
    ctx.fillStyle = blendHex(pal[1], pal[0], zn);
    ctx.beginPath();
    ctx.arc(sx, sy, sz, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

// ── Component ────────────────────────────────────────────────────────────────

interface Props {
  getFrequencyData: () => Float32Array | Uint8Array;
  settings: VisualizerSettings;
}

export function AudioVisualizer({ getFrequencyData, settings }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef(0);
  const rsRef = useRef<RS>({ rotAngle: 0, pulse: 0, rotX: 0.45, rotY: 0.3 });
  const dragRef = useRef({ active: false, px: 0, py: 0 });

  // Keep latest props accessible inside RAF without re-creating the loop
  const settingsRef = useRef(settings);
  const getFreqRef = useRef(getFrequencyData);
  settingsRef.current = settings;
  getFreqRef.current = getFrequencyData;

  // Resize — uses parent.offsetWidth (canvas.clientWidth may be 0 before layout)
  useEffect(() => {
    const resize = () => {
      const canvas = canvasRef.current;
      const wrap = wrapRef.current;
      if (!canvas || !wrap) return;
      const dpr = window.devicePixelRatio || 1;
      const w = wrap.offsetWidth, h = wrap.offsetHeight;
      if (!w || !h) return;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      // setTransform resets the matrix — avoids compounding scale on repeated resize
      canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    if (wrapRef.current) ro.observe(wrapRef.current);
    window.addEventListener('resize', resize);
    return () => { ro.disconnect(); window.removeEventListener('resize', resize); };
  }, []);

  // Pointer drag for 3D rotation
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const dr = dragRef.current;
    const rs = rsRef.current;
    const onDown = (e: PointerEvent) => { dr.active = true; dr.px = e.clientX; dr.py = e.clientY; };
    const onUp = () => { dr.active = false; };
    const onMove = (e: PointerEvent) => {
      if (!dr.active) return;
      rs.rotY += (e.clientX - dr.px) * 0.006;
      rs.rotX += (e.clientY - dr.py) * 0.006;
      dr.px = e.clientX; dr.py = e.clientY;
    };
    wrap.addEventListener('pointerdown', onDown);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointermove', onMove);
    return () => {
      wrap.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointermove', onMove);
    };
  }, []);

  // RAF render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const tick = () => {
      rafRef.current = requestAnimationFrame(tick);
      const dpr = window.devicePixelRatio || 1;
      const W = canvas.width / dpr, H = canvas.height / dpr;
      if (W < 10 || H < 10) return;

      const s = settingsRef.current;
      const rs = rsRef.current;
      const ad = getFreqRef.current();

      ctx.clearRect(0, 0, W, H);

      let sum = 0, bsum = 0;
      const bc = Math.floor(ad.length * 0.14);
      for (let i = 0; i < ad.length; i++) {
        const v = (ad[i] ?? 0) / 255;
        sum += v;
        if (i < bc) bsum += v;
      }
      const avgVol = (sum / ad.length) * s.gain;
      const bassVol = (bsum / (bc || 1)) * s.gain;
      rs.rotAngle += 0.004 * s.speed;
      rs.pulse += 0.028 + avgVol * 0.055;

      const cx = W / 2, cy = H / 2;
      if (s.style === 'wave')
        renderWaveRing(ctx, cx, cy, avgVol, bassVol, ad, s, rs);
      else
        renderSphere(ctx, cx, cy, avgVol, bassVol, ad, s, rs, dragRef.current.active);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []); // loop is intentionally set up once; all state is via refs

  return (
    <div
      ref={wrapRef}
      className="absolute inset-0"
      style={{ cursor: settings.style === '3d' ? 'grab' : 'default' }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 block w-full h-full" />
    </div>
  );
}
