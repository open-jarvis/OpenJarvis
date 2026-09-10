import React, { Suspense, lazy, useState, useMemo } from 'react';
import type { PetState } from './types';
import { ThreeChibiRobot } from './ThreeChibiRobot';

// Optional Spline loader if a custom scene URL is provided
const Spline = lazy(() => import('@splinetool/react-spline'));

export interface RobotPetProps {
  /** Current animation/voice state */
  state?: PetState | string;
  /** Scale factor (inherited from useFloatingPet) */
  scale?: number;
  /** Whether pet is actively being dragged */
  isDragging?: boolean;
  /** Horizontal drag delta for directional tilt */
  dragDeltaX?: number;
  /** Whether to force external Spline scene instead of procedural 3D Chibi Mascot */
  useSpline?: boolean;
  /** Path or URL to .splinecode scene */
  sceneUrl?: string;
  /** Callback fired if 3D initialization fails */
  onError?: (error: unknown) => void;
  /** Callback fired when 3D completes loading */
  onLoad?: (app: unknown) => void;
  /** Whether to show drop shadow under the robot */
  showShadow?: boolean;
  /** Additional CSS class names */
  className?: string;
  /** Additional inline styles */
  style?: React.CSSProperties;
}

/**
 * Computes visual aura / glow / pulse classes based on the active pet state.
 */
function getRobotStateClasses(state: string, isDragging: boolean): string {
  if (isDragging) {
    return 'scale-[1.03] transition-transform duration-150';
  }

  const s = state.toLowerCase();
  switch (s) {
    case 'review':
    case 'completed':
    case 'cheer':
      return 'animate-[bounce_1.5s_infinite]';

    default:
      return '';
  }
}

/**
 * RobotPet renders the 3D Chibi AI Assistant mascot matching the user's reference design:
 * - Round white glossy helmet head
 * - Dark blue curved visor with smiling neon LED eyes (^ ^) that blink
 * - Cyan ear antennas & headphone ports
 * - Floating white pod body with cyan chest shield (NO LEGS)
 * - Waving left hand with continuous floating bobbing
 * - Smooth head tracking to cursor position
 */
export const RobotPet: React.FC<RobotPetProps> = ({
  state = 'idle',
  scale = 2,
  isDragging = false,
  dragDeltaX = 0,
  useSpline = false,
  sceneUrl,
  onError,
  onLoad,
  className = '',
  style,
}) => {
  const [loadError, setLoadError] = useState<unknown | null>(null);

  const baseWidth = 120;
  const baseHeight = 120;
  const computedWidth = Math.round(baseWidth * (scale / 2));
  const computedHeight = Math.round(baseHeight * (scale / 2));

  const stateClasses = useMemo(
    () => getRobotStateClasses(state, isDragging),
    [state, isDragging]
  );

  // Slight directional tilt when dragged
  const tiltStyle: React.CSSProperties = useMemo(() => {
    if (!isDragging) return {};
    const tiltDeg = Math.max(-12, Math.min(12, dragDeltaX * 1.5));
    return {
      transform: `rotate(${tiltDeg}deg)`,
      transition: 'transform 0.1s ease-out',
    };
  }, [isDragging, dragDeltaX]);

  const handleSplineError = (err: unknown) => {
    setLoadError(err);
    onError?.(err);
  };

  if (loadError) {
    return null;
  }

  return (
    <div
      data-testid="robot-pet"
      data-state={state}
      data-dragging={isDragging ? 'true' : 'false'}
      className={`relative flex flex-col items-center justify-center select-none ${className}`}
      style={{
        width: `${computedWidth}px`,
        height: `${computedHeight}px`,
        ...tiltStyle,
        ...style,
      }}
    >
      {/* 3D Mascot Transparent Canvas Container */}
      <div
        className={`relative w-full h-full overflow-visible pointer-events-auto transition-transform duration-300 ${stateClasses}`}
      >
        {useSpline && sceneUrl ? (
          <Suspense
            fallback={
              <div
                data-testid="robot-pet-loading"
                className="absolute inset-0 flex items-center justify-center bg-cyan-950/20 backdrop-blur-xs animate-pulse rounded-3xl"
              >
                <div className="w-8 h-8 rounded-full border-2 border-cyan-400/40 border-t-cyan-400 animate-spin" />
              </div>
            }
          >
            <Spline
              scene={sceneUrl}
              onLoad={onLoad}
              onError={handleSplineError}
              style={{
                width: '100%',
                height: '100%',
                display: 'block',
                pointerEvents: 'auto',
              }}
            />
          </Suspense>
        ) : (
          /* Exact 3D Chibi Mascot matching the reference photo */
          <ThreeChibiRobot
            state={state}
            isDragging={isDragging}
            dragDeltaX={dragDeltaX}
          />
        )}
      </div>
    </div>
  );
};
