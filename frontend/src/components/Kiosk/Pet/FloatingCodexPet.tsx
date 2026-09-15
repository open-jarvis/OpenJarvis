import React, { useEffect, useMemo, useState } from 'react';
import { CodexPet, DEFAULT_MINTY_MANIFEST } from './CodexPet';
import { PetRenderer, type PetRendererType } from './PetRenderer';
import { parsePetManifest } from './codexPetAtlas';
import { resolvePetState } from './codexPetState';
import { splitCaptionSegments } from '@/components/Chat/voiceTurnRows';
import { useFloatingPet } from '@/hooks/useFloatingPet';
import type { PetManifest, PetPosition, PetSize } from './types';
import type { LocalVoiceStatus } from '@/hooks/voiceStatus';

export interface FloatingCodexPetProps {
  /** Renderer type: 'robot' for 3D mascot or 'sprite' for 2D pixel (defaults to 'robot') */
  petType?: PetRendererType;
  /** Optional custom Spline scene URL or path */
  robotSceneUrl?: string;
  /** Voice status from voice assistant */
  voiceStatus?: LocalVoiceStatus | string | null;
  /** Activity detail for task or animation override */
  activityDetail?: string | null;
  /** Speech text for speech bubble */
  speechText?: string | null;
  /** Caption text alias from voice mode */
  assistantCaptionText?: string | null;
  /** Direct manifest object override */
  manifest?: PetManifest;
  /** URL to pet.json manifest (defaults to '/pets/minty/pet.json') */
  manifestUrl?: string;
  /** Initial spawn position */
  initialPosition?: PetPosition;
  /** Initial spawn placement ('bottom-right' or 'center') */
  initialPlacement?: 'bottom-right' | 'center';
  /** LocalStorage key for position */
  storageKey?: string;
  /** Scale factor override (defaults to manifest.scale ?? 2) */
  scale?: number;
  /** Render mode: 'css' or 'canvas' */
  renderMode?: 'css' | 'canvas';
  /** Whether to show drop shadow */
  showShadow?: boolean;
  /** Enable autonomous wandering when idle */
  enableWandering?: boolean;
  /** Additional CSS class names */
  className?: string;
  /** Additional inline styles */
  style?: React.CSSProperties;
}

/**
 * Loads a PetManifest from a URL or returns fallback DEFAULT_MINTY_MANIFEST on failure.
 */
export async function fetchPetManifest(
  url: string = '/pets/minty/pet.json',
  fetchFn: typeof fetch = typeof fetch !== 'undefined' ? fetch : (globalThis.fetch as typeof fetch),
): Promise<PetManifest> {
  try {
    if (typeof fetchFn !== 'function') {
      return DEFAULT_MINTY_MANIFEST;
    }
    const res = await fetchFn(url);
    if (!res.ok) {
      return DEFAULT_MINTY_MANIFEST;
    }
    const json = await res.json();
    return parsePetManifest(json);
  } catch {
    return DEFAULT_MINTY_MANIFEST;
  }
}

/**
 * FloatingCodexPet overlay component.
 * Assembles floating physics, state resolution, asynchronous manifest loading,
 * sprite rendering, and speech bubble display in a fixed layer.
 */
export function FloatingCodexPet({
  petType: petTypeProp,
  robotSceneUrl,
  voiceStatus,
  activityDetail,
  speechText,
  assistantCaptionText,
  manifest: manifestProp,
  manifestUrl = '/pets/minty/pet.json',
  initialPosition,
  initialPlacement,
  storageKey,
  scale: scaleProp,
  renderMode = 'css',
  showShadow = true,
  enableWandering = true,
  className = '',
  style,
}: FloatingCodexPetProps) {
  const [activeManifest, setActiveManifest] = useState<PetManifest>(
    () => manifestProp ?? DEFAULT_MINTY_MANIFEST,
  );

  // Synchronize manifest if prop changes
  useEffect(() => {
    if (manifestProp) {
      setActiveManifest(manifestProp);
      return;
    }

    let isMounted = true;
    void fetchPetManifest(manifestUrl).then((loaded) => {
      if (isMounted) {
        setActiveManifest(loaded);
      }
    });

    return () => {
      isMounted = false;
    };
  }, [manifestProp, manifestUrl]);

  const baseSize: PetSize = {
    width: activeManifest.size.width,
    height: activeManifest.size.height,
  };

  const {
    position,
    scale,
    setScale,
    isDragging,
    isResizing,
    dragDeltaX,
    petHandlers,
    getResizeHandleProps,
  } = useFloatingPet({
    initialPosition,
    initialPlacement,
    storageKey,
    initialScale: scaleProp ?? activeManifest.scale ?? 2,
    baseSize,
    enableWandering,
  });

  // Dynamically update pet scale when scaleProp changes (e.g. from settings slider)
  useEffect(() => {
    if (scaleProp !== undefined) {
      setScale(scaleProp);
    }
  }, [scaleProp, setScale]);

  const effectiveScale = scaleProp ?? scale;

  const petState = resolvePetState(
    voiceStatus,
    activityDetail,
    isDragging,
    dragDeltaX,
  );

  const effectiveSpeechText = useMemo(() => {
    if (speechText) return speechText;
    if (!assistantCaptionText) return undefined;
    const segments = splitCaptionSegments(assistantCaptionText);
    return segments.slice(-1)[0] ?? assistantCaptionText;
  }, [speechText, assistantCaptionText]);
  const effectiveVoiceStatus = voiceStatus ?? undefined;
  const effectivePetType = petTypeProp ?? (manifestProp ? 'sprite' : 'robot');

  return (
    <div
      data-testid="floating-codex-pet"
      data-state={petState}
      data-dragging={isDragging ? 'true' : 'false'}
      data-resizing={isResizing ? 'true' : 'false'}
      className={`fixed z-40 touch-none select-none group ${className}`}
      style={{
        position: 'fixed',
        left: 0,
        top: 0,
        transform: `translate3d(${position.x}px, ${position.y}px, 0)`,
        zIndex: 40,
        ...style,
      }}
      {...petHandlers}
    >
      <PetRenderer
        petType={effectivePetType}
        robotSceneUrl={robotSceneUrl}
        manifest={activeManifest}
        state={petState}
        scale={effectiveScale}
        renderMode={renderMode}
        isDragging={isDragging}
        dragDeltaX={dragDeltaX}
        speechText={effectiveSpeechText}
        voiceStatus={effectiveVoiceStatus}
        showShadow={showShadow}
      />

      {/* 4 Corner Resize Handles (Similar to ScreenShareView) */}
      <div
        {...getResizeHandleProps('nw')}
        title="Resize Top-Left"
        className="absolute -top-1.5 -left-1.5 w-5 h-5 cursor-nwse-resize touch-none z-20 opacity-0 group-hover:opacity-100 transition-opacity"
      />
      <div
        {...getResizeHandleProps('ne')}
        title="Resize Top-Right"
        className="absolute -top-1.5 -right-1.5 w-5 h-5 cursor-nesw-resize touch-none z-20 opacity-0 group-hover:opacity-100 transition-opacity"
      />
      <div
        {...getResizeHandleProps('sw')}
        title="Resize Bottom-Left"
        className="absolute -bottom-1.5 -left-1.5 w-5 h-5 cursor-nesw-resize touch-none z-20 opacity-0 group-hover:opacity-100 transition-opacity"
      />
      <div
        {...getResizeHandleProps('se')}
        title="Resize Bottom-Right"
        className="absolute -bottom-1.5 -right-1.5 w-5 h-5 cursor-nwse-resize touch-none z-20 opacity-0 group-hover:opacity-100 transition-opacity"
      />
    </div>
  );
}
