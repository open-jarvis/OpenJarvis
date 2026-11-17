import { useEffect, useRef } from 'react';
import type { HudPhase } from '../../hooks/useHudSession';

interface ReactorCoreProps {
  phase: HudPhase;
  /** Nivel de audio actual (0..1): la voz de Jarvis o el micrófono. */
  getLevel: () => number;
}

interface PhaseStyle {
  /** Color principal en formato "r, g, b" para combinar con transparencias. */
  rgb: string;
  /** Multiplicador de la velocidad de giro de los anillos. */
  spin: number;
  /** Brillo base del núcleo cuando no hay sonido. */
  glow: number;
}

const PHASE_STYLES: Record<HudPhase, PhaseStyle> = {
  standby: { rgb: '70, 110, 140', spin: 0.25, glow: 0.25 },
  idle: { rgb: '56, 214, 255', spin: 1, glow: 0.5 },
  hearing: { rgb: '130, 240, 255', spin: 1.6, glow: 0.7 },
  transcribing: { rgb: '255, 181, 71', spin: 2.6, glow: 0.6 },
  thinking: { rgb: '255, 181, 71', spin: 3.4, glow: 0.65 },
  speaking: { rgb: '190, 246, 255', spin: 1.3, glow: 0.8 },
};

const TICK_COUNT = 72;
const BAR_COUNT = 64;
const FULL_TURN = Math.PI * 2;
/** El nivel de voz ronda 0.05–0.3; se amplifica para que el movimiento se note. */
const LEVEL_GAIN = 4;

/** Anillos de arcos: radio relativo, grosor, segmentos, giro (rad/s) y opacidad. */
const ARC_RINGS = [
  { radius: 0.9, width: 1.5, segments: 3, gap: 0.5, speed: 0.12, alpha: 0.55 },
  { radius: 0.78, width: 4, segments: 2, gap: 1.1, speed: -0.2, alpha: 0.4 },
  { radius: 0.47, width: 2, segments: 5, gap: 0.35, speed: 0.34, alpha: 0.6 },
];

/**
 * Núcleo central del HUD. Se dibuja en canvas porque cada cuadro depende del
 * nivel de audio: animarlo con estado de React re-renderizaría toda la pantalla.
 */
export function ReactorCore({ phase, getLevel }: ReactorCoreProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // En refs para que cambiar de fase no reinicie el bucle de animación.
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const getLevelRef = useRef(getLevel);
  getLevelRef.current = getLevel;

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let frameId = 0;
    let lastTime = performance.now();
    let rotation = 0;
    let level = 0;

    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      canvas.width = canvas.clientWidth * ratio;
      canvas.height = canvas.clientHeight * ratio;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();

    const draw = (time: number) => {
      const elapsed = Math.min((time - lastTime) / 1000, 0.1);
      lastTime = time;
      const style = PHASE_STYLES[phaseRef.current];
      const color = (alpha: number) => `rgba(${style.rgb}, ${alpha})`;

      // Sube rápido y baja despacio, como un vúmetro: evita el parpadeo.
      const target = Math.min(1, getLevelRef.current() * LEVEL_GAIN);
      level += (target - level) * (target > level ? 0.5 : 0.12);
      rotation += elapsed * style.spin * (reducedMotion ? 0.15 : 1);

      const { width, height } = canvas;
      const centerX = width / 2;
      const centerY = height / 2;
      const size = Math.min(width, height) / 2;
      context.clearRect(0, 0, width, height);
      context.lineCap = 'round';

      // Corona de marcas, con una marca larga cada seis.
      context.lineWidth = Math.max(1, size * 0.004);
      for (let i = 0; i < TICK_COUNT; i += 1) {
        const angle = (i / TICK_COUNT) * FULL_TURN + rotation * 0.05;
        const inner = size * (i % 6 === 0 ? 0.93 : 0.96);
        context.strokeStyle = color(i % 6 === 0 ? 0.6 : 0.25);
        context.beginPath();
        context.moveTo(centerX + Math.cos(angle) * inner, centerY + Math.sin(angle) * inner);
        context.lineTo(centerX + Math.cos(angle) * size * 0.99, centerY + Math.sin(angle) * size * 0.99);
        context.stroke();
      }

      for (const ring of ARC_RINGS) {
        const arcLength = FULL_TURN / ring.segments - ring.gap;
        context.strokeStyle = color(ring.alpha);
        context.lineWidth = Math.max(1, (ring.width * size) / 220);
        for (let segment = 0; segment < ring.segments; segment += 1) {
          const start = rotation * ring.speed * 5 + (segment / ring.segments) * FULL_TURN;
          context.beginPath();
          context.arc(centerX, centerY, size * ring.radius, start, start + arcLength);
          context.stroke();
        }
      }

      // Barras radiales: su largo sigue al sonido, con una ondulación propia
      // por barra para que parezca un espectro y no un anillo uniforme.
      context.lineWidth = Math.max(1.5, size * 0.011);
      for (let i = 0; i < BAR_COUNT; i += 1) {
        const angle = (i / BAR_COUNT) * FULL_TURN - Math.PI / 2;
        const ripple = 0.5 + 0.5 * Math.sin(i * 0.9 + time * 0.006) * Math.sin(i * 0.37 - time * 0.004);
        const length = size * (0.015 + level * 0.16 * (0.35 + ripple));
        const inner = size * 0.56;
        context.strokeStyle = color(0.35 + level * 0.6);
        context.beginPath();
        context.moveTo(centerX + Math.cos(angle) * inner, centerY + Math.sin(angle) * inner);
        context.lineTo(
          centerX + Math.cos(angle) * (inner + length),
          centerY + Math.sin(angle) * (inner + length),
        );
        context.stroke();
      }

      // Núcleo: respira lento en reposo y late con la voz.
      const breath = reducedMotion ? 0 : Math.sin(time * 0.0016) * 0.03;
      const coreRadius = size * (0.3 + breath + level * 0.1);
      const intensity = Math.min(1, style.glow + level * 0.5);
      const gradient = context.createRadialGradient(centerX, centerY, 0, centerX, centerY, coreRadius * 1.5);
      gradient.addColorStop(0, `rgba(255, 255, 255, ${0.85 * intensity})`);
      gradient.addColorStop(0.25, color(0.75 * intensity));
      gradient.addColorStop(0.65, color(0.18 * intensity));
      gradient.addColorStop(1, color(0));
      context.fillStyle = gradient;
      context.beginPath();
      context.arc(centerX, centerY, coreRadius * 1.5, 0, FULL_TURN);
      context.fill();

      context.strokeStyle = color(0.9);
      context.lineWidth = Math.max(1, size * 0.006);
      context.beginPath();
      context.arc(centerX, centerY, coreRadius * 0.72, 0, FULL_TURN);
      context.stroke();

      frameId = requestAnimationFrame(draw);
    };
    frameId = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} className="hud-core-canvas" aria-hidden="true" />;
}
