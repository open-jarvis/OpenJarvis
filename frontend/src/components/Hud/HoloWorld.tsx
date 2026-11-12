import { useEffect, useRef } from 'react';

/**
 * Full-screen canvas "virtual tech world": a perspective grid floor that
 * scrolls toward the viewer, a 3D particle field, floating wireframe
 * polyhedra and touch/click shockwaves. Pure canvas — no WebGL dependency.
 *
 * `energy` (0..1) speeds the world up while Jarvis is thinking or speaking.
 */

type Vec3 = [number, number, number];

interface Burst {
  x: number;
  y: number;
  t: number;
  sparks: { a: number; v: number; r: number }[];
}

interface Trail {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
}

const ICOSA_VERTS: Vec3[] = (() => {
  const p = (1 + Math.sqrt(5)) / 2;
  const v: Vec3[] = [
    [-1, p, 0], [1, p, 0], [-1, -p, 0], [1, -p, 0],
    [0, -1, p], [0, 1, p], [0, -1, -p], [0, 1, -p],
    [p, 0, -1], [p, 0, 1], [-p, 0, -1], [-p, 0, 1],
  ];
  return v.map(([x, y, z]) => {
    const l = Math.hypot(x, y, z);
    return [x / l, y / l, z / l] as Vec3;
  });
})();

const ICOSA_EDGES: [number, number][] = (() => {
  const edges: [number, number][] = [];
  for (let i = 0; i < ICOSA_VERTS.length; i++) {
    for (let j = i + 1; j < ICOSA_VERTS.length; j++) {
      const [a, b] = [ICOSA_VERTS[i], ICOSA_VERTS[j]];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
      if (d < 1.1) edges.push([i, j]);
    }
  }
  return edges;
})();

function rotate([x, y, z]: Vec3, ax: number, ay: number): Vec3 {
  const cy = Math.cos(ay), sy = Math.sin(ay);
  const x1 = x * cy + z * sy;
  const z1 = -x * sy + z * cy;
  const cx = Math.cos(ax), sx = Math.sin(ax);
  return [x1, y * cx - z1 * sx, y * sx + z1 * cx];
}

export function HoloWorld({ energy = 0 }: { energy?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const energyRef = useRef(energy);
  energyRef.current = energy;

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext('2d')!;
    let w = 0, h = 0, dpr = 1;
    let raf = 0;
    let last = performance.now();
    let gridOffset = 0;
    let smoothEnergy = 0;
    const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
    const bursts: Burst[] = [];
    const trails: Trail[] = [];
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const stars = Array.from({ length: 260 }, () => ({
      x: (Math.random() - 0.5) * 2000,
      y: (Math.random() - 0.5) * 1400,
      z: Math.random() * 1600 + 50,
    }));

    const shapes = Array.from({ length: 7 }, (_, i) => ({
      x: (i % 2 ? 1 : -1) * (380 + Math.random() * 520),
      y: (Math.random() - 0.6) * 420,
      z: 500 + Math.random() * 900,
      s: 40 + Math.random() * 70,
      ax: Math.random() * 6,
      ay: Math.random() * 6,
      sp: 0.15 + Math.random() * 0.35,
    }));

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener('resize', resize);

    const onMove = (e: PointerEvent) => {
      pointer.tx = (e.clientX / w - 0.5) * 2;
      pointer.ty = (e.clientY / h - 0.5) * 2;
      if (e.buttons || e.pointerType === 'touch') {
        for (let i = 0; i < 2; i++) {
          trails.push({
            x: e.clientX, y: e.clientY,
            vx: (Math.random() - 0.5) * 60, vy: (Math.random() - 0.5) * 60,
            life: 1,
          });
        }
      }
    };
    const onDown = (e: PointerEvent) => {
      bursts.push({
        x: e.clientX,
        y: e.clientY,
        t: 0,
        sparks: Array.from({ length: 18 }, () => ({
          a: Math.random() * Math.PI * 2,
          v: 120 + Math.random() * 260,
          r: 1 + Math.random() * 2,
        })),
      });
      if (bursts.length > 12) bursts.shift();
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerdown', onDown);

    const frame = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      smoothEnergy += (energyRef.current - smoothEnergy) * Math.min(dt * 3, 1);
      const speed = (reduceMotion ? 0.2 : 1) * (1 + smoothEnergy * 3);
      pointer.x += (pointer.tx - pointer.x) * Math.min(dt * 4, 1);
      pointer.y += (pointer.ty - pointer.y) * Math.min(dt * 4, 1);

      ctx.clearRect(0, 0, w, h);

      // Background gradient
      const bg = ctx.createRadialGradient(w / 2, h * 0.45, 0, w / 2, h * 0.45, Math.max(w, h) * 0.8);
      bg.addColorStop(0, '#04161b');
      bg.addColorStop(0.55, '#020a0e');
      bg.addColorStop(1, '#010406');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);

      const cx = w / 2 - pointer.x * 30;
      const horizon = h * 0.62 - pointer.y * 20;
      const fov = Math.min(w, h) * 0.9;

      // Horizon glow
      const hg = ctx.createLinearGradient(0, horizon - 120, 0, horizon + 40);
      hg.addColorStop(0, 'rgba(0,229,255,0)');
      hg.addColorStop(0.75, `rgba(0,229,255,${0.08 + smoothEnergy * 0.08})`);
      hg.addColorStop(1, 'rgba(0,229,255,0)');
      ctx.fillStyle = hg;
      ctx.fillRect(0, horizon - 120, w, 160);

      // Stars / particles
      for (const s of stars) {
        s.z -= 60 * speed * dt;
        if (s.z < 20) {
          s.z = 1600;
          s.x = (Math.random() - 0.5) * 2000;
          s.y = (Math.random() - 0.5) * 1400;
        }
        const k = fov / s.z;
        const px = cx + (s.x - pointer.x * 80) * k;
        const py = h * 0.45 + (s.y - pointer.y * 60) * k;
        if (px < 0 || px > w || py < 0 || py > h) continue;
        const a = Math.min(1, (1600 - s.z) / 900);
        ctx.fillStyle = `rgba(120,240,255,${a * 0.7})`;
        const r = Math.max(0.4, 1.6 * k * 0.6);
        ctx.fillRect(px, py, r, r);
      }

      // Perspective grid floor
      gridOffset = (gridOffset + dt * 40 * speed) % 40;
      ctx.lineWidth = 1;
      const camH = 120;
      for (let i = 0; i < 40; i++) {
        const z = 40 + i * 40 - gridOffset;
        if (z <= 10) continue;
        const y = horizon + (camH * fov) / z / 3;
        if (y > h) continue;
        const a = Math.min(0.45, 30 / z) * (0.6 + smoothEnergy * 0.4);
        ctx.strokeStyle = `rgba(0,229,255,${a})`;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      for (let i = -24; i <= 24; i++) {
        const xw = i * 60;
        const xNear = cx + (xw * fov) / 40 / 3;
        const xFar = cx + (xw * fov) / 1600 / 3;
        const g = ctx.createLinearGradient(0, horizon, 0, h);
        g.addColorStop(0, 'rgba(0,229,255,0)');
        g.addColorStop(1, `rgba(0,229,255,${0.28 + smoothEnergy * 0.15})`);
        ctx.strokeStyle = g;
        ctx.beginPath();
        ctx.moveTo(xFar, horizon);
        ctx.lineTo(xNear, horizon + (camH * fov) / 40 / 3);
        ctx.stroke();
      }

      // Floating wireframe polyhedra
      for (const sh of shapes) {
        sh.ax += dt * sh.sp * speed;
        sh.ay += dt * sh.sp * 0.8 * speed;
        const k = fov / sh.z;
        const ox = cx + (sh.x - pointer.x * 120) * k;
        const oy = h * 0.42 + (sh.y - pointer.y * 80) * k + Math.sin(now / 1400 + sh.x) * 8;
        const pts = ICOSA_VERTS.map((v) => {
          const r = rotate(v, sh.ax, sh.ay);
          return [ox + r[0] * sh.s * k, oy + r[1] * sh.s * k, r[2]] as Vec3;
        });
        const alpha = Math.min(0.55, 400 / sh.z);
        ctx.strokeStyle = `rgba(0,229,255,${alpha})`;
        ctx.beginPath();
        for (const [a, b] of ICOSA_EDGES) {
          ctx.moveTo(pts[a][0], pts[a][1]);
          ctx.lineTo(pts[b][0], pts[b][1]);
        }
        ctx.stroke();
        ctx.fillStyle = `rgba(160,250,255,${alpha})`;
        for (const p of pts) ctx.fillRect(p[0] - 1, p[1] - 1, 2, 2);
      }

      // Drag trails
      ctx.globalCompositeOperation = 'lighter';
      for (let i = trails.length - 1; i >= 0; i--) {
        const t = trails[i];
        t.life -= dt * 1.6;
        if (t.life <= 0) { trails.splice(i, 1); continue; }
        t.x += t.vx * dt;
        t.y += t.vy * dt;
        ctx.fillStyle = `rgba(0,229,255,${t.life * 0.8})`;
        ctx.beginPath();
        ctx.arc(t.x, t.y, 2.5 * t.life + 0.5, 0, Math.PI * 2);
        ctx.fill();
      }

      // Touch shockwaves
      for (let i = bursts.length - 1; i >= 0; i--) {
        const b = bursts[i];
        b.t += dt;
        const p = b.t / 0.9;
        if (p >= 1) { bursts.splice(i, 1); continue; }
        const ease = 1 - Math.pow(1 - p, 3);
        // Outer ring
        ctx.strokeStyle = `rgba(0,229,255,${(1 - p) * 0.9})`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(b.x, b.y, 10 + ease * 90, 0, Math.PI * 2);
        ctx.stroke();
        // Rotating hexagon
        ctx.lineWidth = 1;
        ctx.strokeStyle = `rgba(140,255,240,${(1 - p) * 0.7})`;
        ctx.beginPath();
        for (let k = 0; k <= 6; k++) {
          const a = (k / 6) * Math.PI * 2 + p * 1.5;
          const r = 6 + ease * 50;
          const x = b.x + Math.cos(a) * r, y = b.y + Math.sin(a) * r;
          if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        // Tick arcs
        ctx.strokeStyle = `rgba(0,229,255,${(1 - p) * 0.6})`;
        for (let k = 0; k < 4; k++) {
          const a = (k / 4) * Math.PI * 2 - p * 2;
          ctx.beginPath();
          ctx.arc(b.x, b.y, 20 + ease * 120, a, a + 0.5);
          ctx.stroke();
        }
        // Sparks
        for (const s of b.sparks) {
          const d = s.v * ease;
          ctx.fillStyle = `rgba(180,255,255,${1 - p})`;
          ctx.fillRect(b.x + Math.cos(s.a) * d, b.y + Math.sin(s.a) * d, s.r, s.r);
        }
        // Core flash
        if (p < 0.25) {
          const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, 40);
          g.addColorStop(0, `rgba(0,229,255,${0.5 * (1 - p * 4)})`);
          g.addColorStop(1, 'rgba(0,229,255,0)');
          ctx.fillStyle = g;
          ctx.fillRect(b.x - 40, b.y - 40, 80, 80);
        }
      }
      ctx.globalCompositeOperation = 'source-over';

      // Scanline sweep
      const sweepY = ((now / 6000) % 1) * h;
      const sg = ctx.createLinearGradient(0, sweepY - 60, 0, sweepY);
      sg.addColorStop(0, 'rgba(0,229,255,0)');
      sg.addColorStop(1, 'rgba(0,229,255,0.05)');
      ctx.fillStyle = sg;
      ctx.fillRect(0, sweepY - 60, w, 60);

      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onDown);
    };
  }, []);

  return <canvas ref={canvasRef} className="hud-world" aria-hidden="true" />;
}
