import { useEffect, useRef } from 'react';
import type { JarvisVoiceState } from './voiceAdapter';

interface Particle {
  x: number;
  y: number;
  size: number;
  depth: number;
  phase: number;
}

function seededParticles(count: number): Particle[] {
  let seed = 0x5f3759df;
  const random = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0xffffffff;
  };
  return Array.from({ length: count }, () => ({
    x: random(),
    y: random(),
    size: 0.45 + random() * 1.7,
    depth: 0.22 + random() * 0.78,
    phase: random() * Math.PI * 2,
  }));
}

function effectiveEnergy(state: JarvisVoiceState, level: number, time: number): number {
  if (state === 'speaking') {
    const fallbackEnvelope = 0.3 + Math.abs(Math.sin(time * 0.0067)) * 0.34
      + Math.abs(Math.sin(time * 0.0161)) * 0.18;
    return Math.max(level, fallbackEnvelope);
  }
  if (state === 'listening') return 0.36 + Math.sin(time * 0.0042) * 0.12;
  if (state === 'processing') return 0.48;
  return 0.14;
}

export function CosmicField({
  state,
  volumeLevel,
  tier,
}: {
  state: JarvisVoiceState;
  volumeLevel: number;
  tier: 1 | 2 | 3 | 4;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = canvas?.parentElement;
    const context = canvas?.getContext('2d');
    if (!canvas || !container || !context || tier === 4) return undefined;

    const particles = seededParticles(tier === 1 ? 88 : tier === 2 ? 58 : 34);
    let frame = 0;
    let width = 1;
    let height = 1;
    let visible = document.visibilityState === 'visible';

    const resize = () => {
      const rect = container.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, tier === 1 ? 1.5 : 1.15);
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const render = (time: number) => {
      context.clearRect(0, 0, width, height);
      const energy = effectiveEnergy(state, volumeLevel, time);
      const centerX = width * 0.5;
      const centerY = height * 0.44;
      const pulse = 0.5 + Math.sin(time * 0.0036) * 0.5;

      if (state === 'processing') {
        context.save();
        context.translate(centerX, centerY);
        context.rotate(time * 0.00012);
        context.strokeStyle = `rgba(218,231,240,${0.08 + pulse * 0.08})`;
        context.lineWidth = 0.8;
        context.setLineDash([2, 11]);
        context.beginPath();
        context.ellipse(0, 0, width * 0.22, height * 0.33, -0.18, 0, Math.PI * 2);
        context.stroke();
        context.restore();
      }

      for (const particle of particles) {
        let x = particle.x * width;
        let y = particle.y * height;
        const wave = Math.sin(time * 0.00045 + particle.phase);

        if (state === 'listening') {
          const attraction = (0.035 + pulse * 0.035) * particle.depth;
          x += (centerX - x) * attraction;
          y += (centerY - y) * attraction;
        } else if (state === 'processing') {
          const dx = x - centerX;
          const dy = y - centerY;
          const angle = time * 0.00008 * particle.depth;
          x = centerX + dx * Math.cos(angle) - dy * Math.sin(angle);
          y = centerY + dx * Math.sin(angle) + dy * Math.cos(angle);
        } else if (state === 'speaking') {
          const dx = x - centerX;
          const dy = y - centerY;
          const expansion = 1 + energy * 0.035 * Math.sin(time * 0.012 + particle.phase);
          x = centerX + dx * expansion;
          y = centerY + dy * expansion;
        } else {
          x += wave * 5 * particle.depth;
          y += Math.cos(time * 0.00038 + particle.phase) * 3 * particle.depth;
        }

        const twinkle = 0.22 + (0.5 + wave * 0.5) * 0.58 + energy * 0.17;
        context.fillStyle = `rgba(232,240,246,${Math.min(0.92, twinkle * particle.depth)})`;
        context.shadowColor = 'rgba(211,230,242,0.55)';
        context.shadowBlur = particle.size * (2 + energy * 5);
        context.beginPath();
        context.arc(x, y, particle.size * (0.65 + energy * 0.38), 0, Math.PI * 2);
        context.fill();
      }
      context.shadowBlur = 0;
      if (visible) frame = window.requestAnimationFrame(render);
    };

    const onVisibility = () => {
      const nextVisible = document.visibilityState === 'visible';
      if (nextVisible === visible) return;
      visible = nextVisible;
      if (visible) frame = window.requestAnimationFrame(render);
      else window.cancelAnimationFrame(frame);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    document.addEventListener('visibilitychange', onVisibility);
    resize();
    frame = window.requestAnimationFrame(render);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [state, tier, volumeLevel]);

  return <canvas ref={canvasRef} className="jarvis-avatar__field" aria-hidden="true" />;
}
