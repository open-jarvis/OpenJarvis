import { useCallback, useEffect, useRef, useState } from 'react';
import {
  clampPosition,
  computeHandleResize,
  getInitialPosition,
  type Dimensions,
  type Point,
  type ResizeHandle,
} from '@/utils/floatingGeometry';

export interface UseDraggableResizableOptions {
  initialWidth?: number;
  initialHeight?: number;
  aspectRatio?: number;
  minWidth?: number;
  maxWidth?: number;
  minHeight?: number;
  maxHeight?: number;
  offset?: { top?: number; right?: number };
  initialPlacement?: 'top-right' | 'center';
  enableWheelZoom?: boolean;
}

export const getViewportBounds = (
  customWindow?: { innerWidth: number; innerHeight: number } | Window,
): Dimensions => {
  const win = customWindow ?? (typeof window !== 'undefined' ? window : undefined);
  if (win && win.innerWidth > 0 && win.innerHeight > 0) {
    return { width: win.innerWidth, height: win.innerHeight };
  }
  return { width: 1920, height: 1080 };
};

export const getMaxWidthForViewport = (
  aspectRatio: number,
  customWindow?: { innerWidth: number; innerHeight: number } | Window,
): number => {
  const bounds = getViewportBounds(customWindow);
  const ratio = aspectRatio > 0 ? aspectRatio : 16 / 9;
  return Math.max(300, Math.min(bounds.width, Math.round(bounds.height * ratio)));
};

export function useDraggableResizable(options: UseDraggableResizableOptions = {}) {
  const {
    aspectRatio = 16 / 9,
    minWidth = 160,
    offset = { top: 72, right: 24 },
    initialPlacement = 'top-right',
    enableWheelZoom = true,
  } = options;

  const ratio = aspectRatio > 0 ? aspectRatio : 16 / 9;
  const initialWidth =
    options.initialWidth ??
    (initialPlacement === 'center'
      ? Math.min(Math.round(getViewportBounds().width * 0.72), 1100)
      : 380);
  const initialHeight = options.initialHeight ?? Math.round(initialWidth / ratio);
  const [size, setSize] = useState<Dimensions>({ width: initialWidth, height: initialHeight });
  const [position, setPosition] = useState<Point>(() => {
    const bounds = getViewportBounds();
    return getInitialPosition(
      { width: initialWidth, height: initialHeight },
      bounds,
      offset,
      initialPlacement,
    );
  });

  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const restoreBoundsRef = useRef<{ position: Point; size: Dimensions } | null>(null);

  const dragStateRef = useRef<{
    startX: number;
    startY: number;
    startPosX: number;
    startPosY: number;
  } | null>(null);

  const resizeStateRef = useRef<{
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
    startPosX: number;
    startPosY: number;
    handle: ResizeHandle;
  } | null>(null);

  // Re-clamp on window resize
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleWindowResize = () => {
      const bounds = getViewportBounds();
      setPosition((prev) => clampPosition(prev, size, bounds));
    };
    window.addEventListener('resize', handleWindowResize);
    return () => window.removeEventListener('resize', handleWindowResize);
  }, [size]);

  const toggleMaximize = useCallback(() => {
    const bounds = getViewportBounds();

    if (isMaximized) {
      // Restore
      const restore = restoreBoundsRef.current ?? {
        position: getInitialPosition(
          { width: initialWidth, height: initialHeight },
          bounds,
          offset,
          initialPlacement,
        ),
        size: { width: initialWidth, height: initialHeight },
      };
      setSize(restore.size);
      setPosition(clampPosition(restore.position, restore.size, bounds));
      setIsMaximized(false);
    } else {
      // Maximize to full viewport
      restoreBoundsRef.current = { position, size };
      setSize({ width: bounds.width, height: bounds.height });
      setPosition({ x: 0, y: 0 });
      setIsMaximized(true);
    }
  }, [initialHeight, initialPlacement, initialWidth, isMaximized, offset, position, size]);

  const zoom = useCallback(
    (deltaW: number, originClient?: Point) => {
      const bounds = getViewportBounds();
      const currentRatio = ratio > 0 ? ratio : 16 / 9;
      const currentMaxWidth = options.maxWidth ?? getMaxWidthForViewport(currentRatio);
      const currentMinWidth = options.minWidth ?? minWidth;

      setIsMaximized(false);
      setSize((prevSize) => {
        const targetW = Math.min(
          currentMaxWidth,
          Math.max(currentMinWidth, prevSize.width + deltaW),
        );
        const targetH = Math.round(targetW / currentRatio);
        if (targetW === prevSize.width) return prevSize;

        setPosition((prevPos) => {
          const actualDeltaW = targetW - prevSize.width;
          const actualDeltaH = targetH - prevSize.height;

          let fractionX = 0.5;
          let fractionY = 0.5;
          if (originClient && prevSize.width > 0 && prevSize.height > 0) {
            fractionX = Math.min(Math.max((originClient.x - prevPos.x) / prevSize.width, 0), 1);
            fractionY = Math.min(Math.max((originClient.y - prevPos.y) / prevSize.height, 0), 1);
          }

          const targetPos = {
            x: prevPos.x - actualDeltaW * fractionX,
            y: prevPos.y - actualDeltaH * fractionY,
          };
          return clampPosition(targetPos, { width: targetW, height: targetH }, bounds);
        });

        return { width: targetW, height: targetH };
      });
    },
    [minWidth, options.maxWidth, options.minWidth, ratio],
  );

  const onCardPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return; // Only primary button
      const target = e.currentTarget as HTMLElement;
      try {
        target.setPointerCapture?.(e.pointerId);
      } catch {}

      dragStateRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startPosX: position.x,
        startPosY: position.y,
      };
      setIsDragging(true);
    },
    [position],
  );

  const onCardPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragStateRef.current) return;
      const dx = e.clientX - dragStateRef.current.startX;
      const dy = e.clientY - dragStateRef.current.startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        setIsMaximized(false);
      }
      const newPos = {
        x: dragStateRef.current.startPosX + dx,
        y: dragStateRef.current.startPosY + dy,
      };
      const bounds = getViewportBounds();
      setPosition(clampPosition(newPos, size, bounds));
    },
    [size],
  );

  const onCardPointerUp = useCallback((e: React.PointerEvent) => {
    if (!dragStateRef.current) return;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch {}
    dragStateRef.current = null;
    setIsDragging(false);
  }, []);

  const onCardWheel = useCallback(
    (e: React.WheelEvent) => {
      if (!enableWheelZoom) return;
      e.stopPropagation();
      const deltaW = e.deltaY < 0 ? 50 : -50;
      zoom(deltaW, { x: e.clientX, y: e.clientY });
    },
    [enableWheelZoom, zoom],
  );

  const onResizePointerDown = useCallback(
    (e: React.PointerEvent, handle: ResizeHandle = 'se') => {
      if (e.button !== 0) return;
      e.stopPropagation();
      const target = e.currentTarget as HTMLElement;
      try {
        target.setPointerCapture?.(e.pointerId);
      } catch {}

      resizeStateRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startWidth: size.width,
        startHeight: size.height,
        startPosX: position.x,
        startPosY: position.y,
        handle,
      };
      setIsResizing(true);
      if (isMaximized) {
        setIsMaximized(false);
      }
    },
    [isMaximized, position.x, position.y, size.height, size.width],
  );

  const onResizePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!resizeStateRef.current) return;
      e.stopPropagation();
      const dx = e.clientX - resizeStateRef.current.startX;
      const dy = e.clientY - resizeStateRef.current.startY;
      const bounds = getViewportBounds();

      const { position: newPos, size: newSize } = computeHandleResize(
        {
          startPos: {
            x: resizeStateRef.current.startPosX,
            y: resizeStateRef.current.startPosY,
          },
          startSize: {
            width: resizeStateRef.current.startWidth,
            height: resizeStateRef.current.startHeight,
          },
          handle: resizeStateRef.current.handle,
        },
        dx,
        dy,
        {
          minWidth: options.minWidth ?? minWidth,
          maxWidth: options.maxWidth ?? bounds.width,
          minHeight: options.minHeight ?? 100,
          maxHeight: options.maxHeight ?? bounds.height,
          viewport: bounds,
        },
      );
      setSize(newSize);
      setPosition(newPos);
    },
    [minWidth, options.maxHeight, options.maxWidth, options.minHeight, options.minWidth],
  );

  const onResizePointerUp = useCallback((e: React.PointerEvent) => {
    if (!resizeStateRef.current) return;
    e.stopPropagation();
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch {}
    resizeStateRef.current = null;
    setIsResizing(false);
  }, []);

  const getResizeHandleProps = useCallback(
    (handle: ResizeHandle) => ({
      onPointerDown: (e: React.PointerEvent) => onResizePointerDown(e, handle),
      onPointerMove: onResizePointerMove,
      onPointerUp: onResizePointerUp,
      onPointerCancel: onResizePointerUp,
    }),
    [onResizePointerDown, onResizePointerMove, onResizePointerUp],
  );

  return {
    position,
    size,
    isDragging,
    isResizing,
    isMaximized,
    toggleMaximize,
    zoom,
    setPosition,
    setSize,
    getResizeHandleProps,
    cardHandlers: {
      onPointerDown: onCardPointerDown,
      onPointerMove: onCardPointerMove,
      onPointerUp: onCardPointerUp,
      onPointerCancel: onCardPointerUp,
      onWheel: onCardWheel,
    },
    resizeHandlers: {
      onPointerDown: (e: React.PointerEvent) => onResizePointerDown(e, 'se'),
      onPointerMove: onResizePointerMove,
      onPointerUp: onResizePointerUp,
      onPointerCancel: onResizePointerUp,
    },
  };
}
