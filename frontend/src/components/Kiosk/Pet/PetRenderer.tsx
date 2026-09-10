import React, { useState, useEffect } from 'react';
import { LegacySpritePet } from './LegacySpritePet';
import { RobotPet } from './RobotPet';
import { CodexPetSpeechBubble } from './CodexPetSpeechBubble';
import { DEFAULT_MINTY_MANIFEST } from './CodexPet';
import type { PetManifest, PetPosition, PetState } from './types';

export type PetRendererType = 'robot' | 'sprite';

export interface PetRendererProps {
  /** Chosen renderer type: 'robot' for 3D Spline, 'sprite' for 2D pixel */
  petType?: PetRendererType;
  /** Path/URL to Spline scene file */
  robotSceneUrl?: string;
  /** Manifest for 2D sprite fallback */
  manifest?: PetManifest;
  /** Current state */
  state?: PetState | string;
  /** Scale factor */
  scale?: number;
  /** Render mode for legacy sprite: 'css' | 'canvas' */
  renderMode?: 'css' | 'canvas';
  /** Whether pet is being dragged */
  isDragging?: boolean;
  /** Horizontal drag delta */
  dragDeltaX?: number;
  /** Custom speech bubble React element */
  speechBubble?: React.ReactNode;
  /** Speech text for standard bubble */
  speechText?: string;
  /** Voice status */
  voiceStatus?: string;
  /** Whether to show drop shadow */
  showShadow?: boolean;
  /** Absolute coordinates if positioned externally */
  position?: PetPosition;
  /** Callback fired if 3D initialization fails */
  onFallback?: (error: unknown) => void;
  /** Additional CSS class names */
  className?: string;
  /** Additional inline styles */
  style?: React.CSSProperties;
  /** Mouse and pointer event handlers */
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  onDoubleClick?: React.MouseEventHandler<HTMLDivElement>;
  onPointerDown?: React.PointerEventHandler<HTMLDivElement>;
  onPointerMove?: React.PointerEventHandler<HTMLDivElement>;
  onPointerUp?: React.PointerEventHandler<HTMLDivElement>;
  onPointerCancel?: React.PointerEventHandler<HTMLDivElement>;
}

/**
 * Checks if WebGL is supported in the current runtime environment.
 */
export function isWebGLSupported(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch {
    return false;
  }
}

interface ErrorBoundaryProps {
  fallback: React.ReactNode;
  onError?: (err: unknown) => void;
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class PetErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    this.props.onError?.(error);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

/**
 * PetRenderer acts as a strategy dispatcher between modern 3D Robot Mascot (Spline)
 * and Legacy 2D Sprite Pet (Minty).
 * Automatically detects WebGL support and falls back gracefully on any runtime failure.
 */
export const PetRenderer: React.FC<PetRendererProps> = ({
  petType = 'robot',
  robotSceneUrl = '/pets/robot/scene.splinecode',
  manifest = DEFAULT_MINTY_MANIFEST,
  state = 'idle',
  scale = 2,
  renderMode = 'css',
  isDragging = false,
  dragDeltaX = 0,
  speechBubble,
  speechText,
  voiceStatus,
  showShadow = true,
  position,
  onFallback,
  className = '',
  style,
  onClick,
  onDoubleClick,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
}) => {
  const [hasRuntimeError, setHasRuntimeError] = useState(false);
  const [webglAvailable, setWebglAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    setWebglAvailable(isWebGLSupported());
  }, []);

  const handleFallback = (err: unknown) => {
    setHasRuntimeError(true);
    onFallback?.(err);
  };

  const spriteFallbackElement = (
    <LegacySpritePet
      manifest={manifest}
      state={state}
      scale={scale}
      renderMode={renderMode}
      isDragging={isDragging}
      speechBubble={speechBubble}
      speechText={speechText}
      voiceStatus={voiceStatus}
      showShadow={showShadow}
      position={position}
      className={className}
      style={style}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
    />
  );

  // If user requested sprite, or WebGL is not available, or runtime error occurred -> render legacy sprite
  const shouldUseSprite =
    petType === 'sprite' ||
    hasRuntimeError ||
    webglAvailable === false;

  if (shouldUseSprite) {
    return spriteFallbackElement;
  }

  const baseWidth = 110;
  const baseHeight = 110;
  const computedWidth = Math.round(baseWidth * (scale / 2));
  const computedHeight = Math.round(baseHeight * (scale / 2));

  const positionStyle: React.CSSProperties = position
    ? {
        position: 'absolute',
        left: 0,
        top: 0,
        transform: `translate3d(${position.x}px, ${position.y}px, 0)`,
      }
    : {};

  return (
    <PetErrorBoundary fallback={spriteFallbackElement} onError={handleFallback}>
      <div
        data-testid="codex-pet"
        data-mascot="robot"
        data-state={state}
        data-dragging={isDragging ? 'true' : 'false'}
        role="img"
        aria-label={`Robot Mascot (3D AI Assistant) - ${state}`}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        className={`relative inline-flex flex-col items-center justify-center select-none touch-none ${className}`}
        style={{
          width: `${computedWidth}px`,
          height: `${computedHeight}px`,
          ...positionStyle,
          ...style,
        }}
      >
        {/* Speech bubble */}
        {speechBubble ? (
          speechBubble
        ) : speechText || voiceStatus === 'speaking' ? (
          <CodexPetSpeechBubble text={speechText} voiceStatus={voiceStatus} />
        ) : null}

        {/* 3D Robot Mascot */}
        <RobotPet
          state={state}
          scale={scale}
          isDragging={isDragging}
          dragDeltaX={dragDeltaX}
          sceneUrl={robotSceneUrl}
          showShadow={showShadow}
          onError={handleFallback}
        />
      </div>
    </PetErrorBoundary>
  );
};
