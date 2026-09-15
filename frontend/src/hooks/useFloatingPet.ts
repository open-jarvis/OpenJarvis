import { useCallback, useEffect, useRef, useState } from 'react';
import {
  computeCornerResize,
  type ResizeCorner,
} from '../utils/floatingGeometry';
import type { PetPosition, PetSize } from '../components/Kiosk/Pet/types';

export const PET_POSITION_STORAGE_KEY = 'openjarvis_kiosk_pet_pos';
export const PET_SCALE_STORAGE_KEY = 'openjarvis_kiosk_pet_scale';
export const DEFAULT_BASE_PET_SIZE: PetSize = { width: 32, height: 32 };
export const DEFAULT_PET_SIZE: PetSize = { width: 64, height: 64 };
export const DEFAULT_SAFE_MARGIN = 16;
export const DEFAULT_OFFSET_RIGHT_VW = 0.06; // 6vw
export const DEFAULT_OFFSET_BOTTOM_VH = 0.12; // 12vh
export const DEFAULT_WANDER_INTERVAL_MS = 10000; // 10s
export const DEFAULT_WANDER_MIN_STEP = 10;
export const DEFAULT_WANDER_MAX_STEP = 25;
export const DEFAULT_PET_SCALE = 2;
export const MIN_PET_SCALE = 1;
export const MAX_PET_SCALE = 8;

export interface PetOffsetConfig {
  rightVw?: number;
  bottomVh?: number;
  rightPx?: number;
  bottomPx?: number;
  placement?: 'bottom-right' | 'center';
}

export interface UseFloatingPetOptions {
  initialPosition?: PetPosition;
  initialPlacement?: 'bottom-right' | 'center';
  initialScale?: number;
  baseSize?: PetSize;
  petSize?: PetSize;
  minScale?: number;
  maxScale?: number;
  safeMargin?: number;
  storageKey?: string;
  scaleStorageKey?: string;
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
  enableWandering?: boolean;
  wanderIntervalMs?: number;
  bounds?: PetSize;
  offset?: PetOffsetConfig;
}

export interface FloatingPetHandlers {
  onPointerDown: (e: React.PointerEvent<HTMLElement>) => void;
  onPointerMove: (e: React.PointerEvent<HTMLElement>) => void;
  onPointerUp: (e: React.PointerEvent<HTMLElement>) => void;
  onPointerCancel: (e: React.PointerEvent<HTMLElement>) => void;
  onDoubleClick: (e: React.MouseEvent<HTMLElement>) => void;
  onWheel?: (e: React.WheelEvent<HTMLElement>) => void;
}

export interface UseFloatingPetResult {
  position: PetPosition;
  scale: number;
  isDragging: boolean;
  isResizing: boolean;
  dragDeltaX: number;
  petHandlers: FloatingPetHandlers;
  getResizeHandleProps: (corner: ResizeCorner) => {
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => void;
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => void;
    onPointerUp: (e: React.PointerEvent<HTMLElement>) => void;
    onPointerCancel: (e: React.PointerEvent<HTMLElement>) => void;
  };
  resetPosition: () => void;
  setPosition: React.Dispatch<React.SetStateAction<PetPosition>>;
  setScale: React.Dispatch<React.SetStateAction<number>>;
}

/**
 * Clamps a 2D pet position within viewport safe margins.
 */
export function clampPetPosition(
  pos: PetPosition,
  petSize: PetSize = DEFAULT_PET_SIZE,
  viewport: PetSize = { width: 1920, height: 1080 },
  margin = DEFAULT_SAFE_MARGIN,
): PetPosition {
  const effectiveMargin = Math.max(0, margin);
  const minX = effectiveMargin;
  const maxX = Math.max(effectiveMargin, viewport.width - petSize.width - effectiveMargin);
  const clampedX = Math.min(Math.max(pos.x, minX), maxX);

  const minY = effectiveMargin;
  const maxY = Math.max(effectiveMargin, viewport.height - petSize.height - effectiveMargin);
  const clampedY = Math.min(Math.max(pos.y, minY), maxY);

  return {
    x: Math.round(clampedX),
    y: Math.round(clampedY),
  };
}

/**
 * Calculates the default bottom-right position (6vw right, 12vh bottom by default),
 * clamped within viewport bounds.
 */
export function calculateDefaultPetPosition(
  viewport: PetSize,
  petSize: PetSize = DEFAULT_PET_SIZE,
  offset?: PetOffsetConfig,
  margin = DEFAULT_SAFE_MARGIN,
  placement: 'bottom-right' | 'center' = 'bottom-right',
): PetPosition {
  if (placement === 'center' || offset?.placement === 'center') {
    const rawX = (viewport.width - petSize.width) / 2;
    const rawY = (viewport.height - petSize.height) / 2;
    return clampPetPosition({ x: rawX, y: rawY }, petSize, viewport, margin);
  }

  const rightOffset =
    offset?.rightPx !== undefined
      ? offset.rightPx
      : viewport.width * (offset?.rightVw ?? DEFAULT_OFFSET_RIGHT_VW);
  const bottomOffset =
    offset?.bottomPx !== undefined
      ? offset.bottomPx
      : viewport.height * (offset?.bottomVh ?? DEFAULT_OFFSET_BOTTOM_VH);

  const rawX = viewport.width - petSize.width - rightOffset;
  const rawY = viewport.height - petSize.height - bottomOffset;

  return clampPetPosition({ x: rawX, y: rawY }, petSize, viewport, margin);
}

/**
 * Reads stored pet position from localStorage or provided storage.
 */
export function readStoredPetPosition(
  storage?: Pick<Storage, 'getItem'>,
  storageKey = PET_POSITION_STORAGE_KEY,
): PetPosition | null {
  try {
    const store =
      storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    if (!store) return null;

    const raw = store.getItem(storageKey);
    if (!raw) return null;

    const parsed = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === 'object' &&
      typeof parsed.x === 'number' &&
      Number.isFinite(parsed.x) &&
      typeof parsed.y === 'number' &&
      Number.isFinite(parsed.y)
    ) {
      return { x: parsed.x, y: parsed.y };
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Reads stored pet scale from localStorage or provided storage.
 */
export function readStoredPetScale(
  storage?: Pick<Storage, 'getItem'>,
  storageKey = PET_SCALE_STORAGE_KEY,
  defaultScale = DEFAULT_PET_SCALE,
  minScale = MIN_PET_SCALE,
  maxScale = MAX_PET_SCALE,
): number {
  try {
    const store =
      storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    if (!store) return defaultScale;

    const raw = store.getItem(storageKey);
    if (!raw) return defaultScale;

    const parsed = Number.parseFloat(raw);
    if (Number.isFinite(parsed) && parsed >= minScale && parsed <= maxScale) {
      return parsed;
    }
    return defaultScale;
  } catch {
    return defaultScale;
  }
}

/**
 * Persists pet scale to storage.
 */
export function persistPetScale(
  scale: number,
  storage?: Pick<Storage, 'setItem'>,
  storageKey = PET_SCALE_STORAGE_KEY,
): void {
  try {
    const store =
      storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    if (!store) return;

    store.setItem(storageKey, String(Math.round(scale * 100) / 100));
  } catch {
    // Gracefully ignore storage errors
  }
}

/**
 * Clears stored pet scale from storage.
 */
export function clearStoredPetScale(
  storage?: Pick<Storage, 'removeItem'>,
  storageKey = PET_SCALE_STORAGE_KEY,
): void {
  try {
    const store =
      storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    if (!store) return;

    store.removeItem(storageKey);
  } catch {
    // Gracefully ignore storage errors
  }
}

/**
 * Persists pet position to storage.
 */
export function persistPetPosition(
  position: PetPosition,
  storage?: Pick<Storage, 'setItem'>,
  storageKey = PET_POSITION_STORAGE_KEY,
): void {
  try {
    const store =
      storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    if (!store) return;

    const raw = JSON.stringify({
      x: Math.round(position.x),
      y: Math.round(position.y),
    });
    store.setItem(storageKey, raw);
  } catch {
    // Gracefully ignore storage write failures in restricted environments
  }
}

/**
 * Clears stored pet position from storage.
 */
export function clearStoredPetPosition(
  storage?: Pick<Storage, 'removeItem'>,
  storageKey = PET_POSITION_STORAGE_KEY,
): void {
  try {
    const store =
      storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    if (!store) return;

    store.removeItem(storageKey);
  } catch {
    // Gracefully ignore storage errors
  }
}

/**
 * Computes an autonomous subtle wandering step (10-25px horizontal) clamped to safe boundaries.
 */
export function calculateWanderStep(
  currentPos: PetPosition,
  petSize: PetSize = DEFAULT_PET_SIZE,
  viewport: PetSize = { width: 1920, height: 1080 },
  stepRange = { min: DEFAULT_WANDER_MIN_STEP, max: DEFAULT_WANDER_MAX_STEP },
  margin = DEFAULT_SAFE_MARGIN,
  randomFn: () => number = Math.random,
): PetPosition {
  const dirX = randomFn() < 0.5 ? -1 : 1;
  const dist = stepRange.min + randomFn() * (stepRange.max - stepRange.min);
  const deltaX = Math.round(dirX * dist);
  const deltaY = Math.round((randomFn() - 0.5) * 6);

  const nextPos: PetPosition = {
    x: currentPos.x + deltaX,
    y: currentPos.y + deltaY,
  };

  return clampPetPosition(nextPos, petSize, viewport, margin);
}

/**
 * React hook managing floating pet physics, pointer-capture dragging, 4-corner resizing,
 * wheel zoom, bounds clamping, localStorage persistence, and idle wandering.
 */
export function useFloatingPet(options: UseFloatingPetOptions = {}): UseFloatingPetResult {
  const {
    initialPosition,
    initialPlacement = 'bottom-right',
    initialScale,
    baseSize = DEFAULT_BASE_PET_SIZE,
    petSize: petSizeProp,
    minScale = MIN_PET_SCALE,
    maxScale = MAX_PET_SCALE,
    safeMargin = DEFAULT_SAFE_MARGIN,
    storageKey = PET_POSITION_STORAGE_KEY,
    scaleStorageKey = PET_SCALE_STORAGE_KEY,
    storage = typeof window !== 'undefined' ? window.localStorage : undefined,
    enableWandering = true,
    wanderIntervalMs = DEFAULT_WANDER_INTERVAL_MS,
    bounds: explicitBounds,
    offset,
  } = options;

  const basePetSize = baseSize ?? { width: 32, height: 32 };

  const [scale, setScale] = useState<number>(() => {
    if (initialScale !== undefined) {
      return Math.min(maxScale, Math.max(minScale, initialScale));
    }
    return readStoredPetScale(storage, scaleStorageKey, DEFAULT_PET_SCALE, minScale, maxScale);
  });

  const activeScale = scale;
  const currentPetSize: PetSize = petSizeProp
    ? {
        width: petSizeProp.width * (activeScale / ((initialScale ?? DEFAULT_PET_SCALE) || 1)),
        height: petSizeProp.height * (activeScale / ((initialScale ?? DEFAULT_PET_SCALE) || 1)),
      }
    : {
        width: Math.round(basePetSize.width * activeScale),
        height: Math.round(basePetSize.height * activeScale),
      };

  const getViewport = useCallback((): PetSize => {
    if (explicitBounds) return explicitBounds;
    if (typeof window !== 'undefined' && window.innerWidth > 0 && window.innerHeight > 0) {
      return { width: window.innerWidth, height: window.innerHeight };
    }
    return { width: 1920, height: 1080 };
  }, [explicitBounds]);

  const [position, setPosition] = useState<PetPosition>(() => {
    const viewport = getViewport();
    if (initialPosition) {
      return clampPetPosition(initialPosition, currentPetSize, viewport, safeMargin);
    }
    const stored = readStoredPetPosition(storage, storageKey);
    if (stored) {
      return clampPetPosition(stored, currentPetSize, viewport, safeMargin);
    }
    return calculateDefaultPetPosition(viewport, currentPetSize, offset, safeMargin, initialPlacement);
  });

  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [dragDeltaX, setDragDeltaX] = useState(0);

  const dragStateRef = useRef<{
    startX: number;
    startY: number;
    startPosX: number;
    startPosY: number;
    lastX: number;
  } | null>(null);

  const resizeStateRef = useRef<{
    startX: number;
    startY: number;
    startPosX: number;
    startPosY: number;
    startWidth: number;
    startHeight: number;
    corner: ResizeCorner;
  } | null>(null);

  const positionRef = useRef(position);
  positionRef.current = position;

  const scaleRef = useRef(scale);
  scaleRef.current = scale;

  // Window resize re-clamping
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleResize = () => {
      const vp = getViewport();
      setPosition((prev) => clampPetPosition(prev, currentPetSize, vp, safeMargin));
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [getViewport, currentPetSize.width, currentPetSize.height, safeMargin]);

  // Autonomous wandering timer when idle
  useEffect(() => {
    if (!enableWandering || isDragging || isResizing) return;

    const timer = setInterval(() => {
      const vp = getViewport();
      setPosition((prev) => calculateWanderStep(prev, currentPetSize, vp, undefined, safeMargin));
    }, wanderIntervalMs);

    return () => clearInterval(timer);
  }, [enableWandering, isDragging, isResizing, getViewport, currentPetSize.width, currentPetSize.height, safeMargin, wanderIntervalMs]);

  const resetPosition = useCallback(() => {
    clearStoredPetPosition(storage, storageKey);
    clearStoredPetScale(storage, scaleStorageKey);
    const defaultScale = initialScale ?? DEFAULT_PET_SCALE;
    setScale(defaultScale);
    const defaultSize: PetSize = {
      width: Math.round(basePetSize.width * defaultScale),
      height: Math.round(basePetSize.height * defaultScale),
    };
    const vp = getViewport();
    const defaultPos = calculateDefaultPetPosition(vp, defaultSize, offset, safeMargin, initialPlacement);
    setPosition(defaultPos);
  }, [basePetSize.height, basePetSize.width, getViewport, initialPlacement, initialScale, offset, safeMargin, scaleStorageKey, storage, storageKey]);

  // Pointer drag handlers
  const onPointerDown = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    const target = e.currentTarget;
    try {
      target.setPointerCapture?.(e.pointerId);
    } catch {}

    dragStateRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startPosX: positionRef.current.x,
      startPosY: positionRef.current.y,
      lastX: e.clientX,
    };
    setIsDragging(true);
    setDragDeltaX(0);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!dragStateRef.current) return;
      const dx = e.clientX - dragStateRef.current.startX;
      const dy = e.clientY - dragStateRef.current.startY;
      const stepDeltaX = e.clientX - dragStateRef.current.lastX;
      dragStateRef.current.lastX = e.clientX;

      if (stepDeltaX !== 0) {
        setDragDeltaX(stepDeltaX);
      }

      const nextPos: PetPosition = {
        x: dragStateRef.current.startPosX + dx,
        y: dragStateRef.current.startPosY + dy,
      };

      const vp = getViewport();
      const clamped = clampPetPosition(nextPos, currentPetSize, vp, safeMargin);
      positionRef.current = clamped;
      setPosition(clamped);
    },
    [getViewport, currentPetSize.width, currentPetSize.height, safeMargin],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!dragStateRef.current) return;
      try {
        e.currentTarget.releasePointerCapture?.(e.pointerId);
      } catch {}
      dragStateRef.current = null;
      setIsDragging(false);
      setDragDeltaX(0);
      persistPetPosition(positionRef.current, storage, storageKey);
    },
    [storage, storageKey],
  );

  const onPointerCancel = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (!dragStateRef.current) return;
    try {
      e.currentTarget.releasePointerCapture?.(e.pointerId);
    } catch {}
    dragStateRef.current = null;
    setIsDragging(false);
    setDragDeltaX(0);
  }, []);

  // Corner resize handlers
  const onResizePointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>, corner: ResizeCorner) => {
      if (e.button !== 0) return;
      e.stopPropagation();
      const target = e.currentTarget;
      try {
        target.setPointerCapture?.(e.pointerId);
      } catch {}

      resizeStateRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startPosX: positionRef.current.x,
        startPosY: positionRef.current.y,
        startWidth: currentPetSize.width,
        startHeight: currentPetSize.height,
        corner,
      };
      setIsResizing(true);
    },
    [currentPetSize.height, currentPetSize.width],
  );

  const onResizePointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!resizeStateRef.current) return;
      e.stopPropagation();

      const dx = e.clientX - resizeStateRef.current.startX;
      const dy = e.clientY - resizeStateRef.current.startY;

      const aspectRatio = basePetSize.width / (basePetSize.height || 1);
      const minW = Math.round(basePetSize.width * minScale);
      const maxW = Math.round(basePetSize.width * maxScale);

      const { position: newPos, size: newSize } = computeCornerResize(
        {
          startPos: {
            x: resizeStateRef.current.startPosX,
            y: resizeStateRef.current.startPosY,
          },
          startSize: {
            width: resizeStateRef.current.startWidth,
            height: resizeStateRef.current.startHeight,
          },
          corner: resizeStateRef.current.corner,
        },
        dx,
        dy,
        aspectRatio,
        minW,
        maxW,
      );

      const calculatedScale = Math.min(
        maxScale,
        Math.max(minScale, Math.round((newSize.width / basePetSize.width) * 100) / 100),
      );

      const vp = getViewport();
      const clampedPos = clampPetPosition(newPos, newSize, vp, safeMargin);

      setScale(calculatedScale);
      positionRef.current = clampedPos;
      setPosition(clampedPos);
    },
    [basePetSize.height, basePetSize.width, getViewport, maxScale, minScale, safeMargin],
  );

  const onResizePointerUp = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!resizeStateRef.current) return;
      e.stopPropagation();
      try {
        e.currentTarget.releasePointerCapture?.(e.pointerId);
      } catch {}
      resizeStateRef.current = null;
      setIsResizing(false);
      persistPetPosition(positionRef.current, storage, storageKey);
      persistPetScale(scaleRef.current, storage, scaleStorageKey);
    },
    [scaleStorageKey, storage, storageKey],
  );

  const getResizeHandleProps = useCallback(
    (corner: ResizeCorner) => ({
      onPointerDown: (e: React.PointerEvent<HTMLElement>) => onResizePointerDown(e, corner),
      onPointerMove: onResizePointerMove,
      onPointerUp: onResizePointerUp,
      onPointerCancel: onResizePointerUp,
    }),
    [onResizePointerDown, onResizePointerMove, onResizePointerUp],
  );

  // Wheel zoom handler
  const onWheel = useCallback(
    (e: React.WheelEvent<HTMLElement>) => {
      e.stopPropagation();
      const zoomStep = e.deltaY < 0 ? 0.25 : -0.25;
      const nextScale = Math.min(
        maxScale,
        Math.max(minScale, Math.round((scaleRef.current + zoomStep) * 4) / 4),
      );
      if (nextScale === scaleRef.current) return;

      const nextWidth = Math.round(basePetSize.width * nextScale);
      const nextHeight = Math.round(basePetSize.height * nextScale);
      const deltaW = nextWidth - currentPetSize.width;
      const deltaH = nextHeight - currentPetSize.height;

      const nextPos: PetPosition = {
        x: positionRef.current.x - deltaW / 2,
        y: positionRef.current.y - deltaH / 2,
      };

      const vp = getViewport();
      const clamped = clampPetPosition(nextPos, { width: nextWidth, height: nextHeight }, vp, safeMargin);

      setScale(nextScale);
      positionRef.current = clamped;
      setPosition(clamped);
      persistPetPosition(clamped, storage, storageKey);
      persistPetScale(nextScale, storage, scaleStorageKey);
    },
    [basePetSize.height, basePetSize.width, currentPetSize.height, currentPetSize.width, getViewport, maxScale, minScale, safeMargin, scaleStorageKey, storage, storageKey],
  );

  const onDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLElement>) => {
      e.stopPropagation();
      resetPosition();
    },
    [resetPosition],
  );

  return {
    position,
    scale,
    isDragging,
    isResizing,
    dragDeltaX,
    petHandlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel,
      onDoubleClick,
      onWheel,
    },
    getResizeHandleProps,
    resetPosition,
    setPosition,
    setScale,
  };
}
