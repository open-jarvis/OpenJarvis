export interface Point {
  x: number;
  y: number;
}

export interface Dimensions {
  width: number;
  height: number;
}

/**
 * Clamps a 2D position within the specified bounds, ensuring the entire
 * element fits within [margin, bounds.dimension - size.dimension - margin].
 * If the viewport/bounds is smaller than size, clamps to margin.
 */
export function clampPosition(
  pos: Point,
  size: Dimensions,
  bounds: Dimensions,
  margin = 0,
): Point {
  const minX = margin;
  const maxX = Math.max(margin, bounds.width - size.width - margin);
  const clampedX = Math.min(Math.max(pos.x, minX), maxX);

  const minY = margin;
  const maxY = Math.max(margin, bounds.height - size.height - margin);
  const clampedY = Math.min(Math.max(pos.y, minY), maxY);

  return {
    x: clampedX,
    y: clampedY,
  };
}

export type ResizeCorner = 'nw' | 'ne' | 'sw' | 'se';

export interface ResizeState {
  startPos: Point;
  startSize: Dimensions;
  corner: ResizeCorner;
}

/**
 * Computes new dimensions and position based on drag delta for a specific corner
 * while strictly preserving aspect ratio and respecting min/max width constraints.
 */
export function computeCornerResize(
  state: ResizeState,
  deltaX: number,
  deltaY: number,
  aspectRatio: number,
  minWidth = 200,
  maxWidth = Number.POSITIVE_INFINITY,
): { position: Point; size: Dimensions } {
  const ratio = aspectRatio > 0 ? aspectRatio : 16 / 9;
  const effectiveMinWidth = minWidth ?? 200;
  const effectiveMaxWidth = maxWidth ?? Number.POSITIVE_INFINITY;

  let deltaWidthX = 0;
  let deltaWidthY = 0;
  switch (state.corner) {
    case 'se':
      deltaWidthX = deltaX;
      deltaWidthY = deltaY * ratio;
      break;
    case 'ne':
      deltaWidthX = deltaX;
      deltaWidthY = -deltaY * ratio;
      break;
    case 'sw':
      deltaWidthX = -deltaX;
      deltaWidthY = deltaY * ratio;
      break;
    case 'nw':
      deltaWidthX = -deltaX;
      deltaWidthY = -deltaY * ratio;
      break;
  }

  const deltaWidth = Math.abs(deltaWidthX) >= Math.abs(deltaWidthY) ? deltaWidthX : deltaWidthY;

  const rawWidth = state.startSize.width + deltaWidth;
  const targetWidth = Math.min(Math.max(rawWidth, effectiveMinWidth), effectiveMaxWidth);
  const newWidth = Math.round(targetWidth);
  const newHeight = Math.round(targetWidth / ratio);

  let newX = state.startPos.x;
  let newY = state.startPos.y;

  switch (state.corner) {
    case 'se':
      // Top-left is fixed
      break;
    case 'sw':
      // Top-right is fixed
      newX = state.startPos.x + (state.startSize.width - newWidth);
      break;
    case 'ne':
      // Bottom-left is fixed
      newY = state.startPos.y + (state.startSize.height - newHeight);
      break;
    case 'nw':
      // Bottom-right is fixed
      newX = state.startPos.x + (state.startSize.width - newWidth);
      newY = state.startPos.y + (state.startSize.height - newHeight);
      break;
  }

  return {
    position: { x: newX, y: newY },
    size: { width: newWidth, height: newHeight },
  };
}

/**
 * Computes new dimensions based on a horizontal drag delta while strictly
 * preserving aspect ratio and respecting min/max width constraints.
 */
export function computeResizeDimensions(
  startWidth: number,
  deltaX: number,
  aspectRatio: number,
  minWidth = 200,
  maxWidth = Number.POSITIVE_INFINITY,
): Dimensions {
  const ratio = aspectRatio > 0 ? aspectRatio : 16 / 9;
  const effectiveMinWidth = minWidth ?? 200;
  const effectiveMaxWidth = maxWidth ?? Number.POSITIVE_INFINITY;

  const rawWidth = startWidth + deltaX;
  const targetWidth = Math.min(Math.max(rawWidth, effectiveMinWidth), effectiveMaxWidth);

  const width = Math.round(targetWidth);
  const height = Math.round(targetWidth / ratio);

  return { width, height };
}

/**
 * Computes the initial default position for a floating window (typically top-right corner),
 * clamped within the bounding viewport.
 */
export function getInitialPosition(
  size: Dimensions,
  bounds: Dimensions,
  offset?: { top?: number; right?: number },
  placement: 'top-right' | 'center' = 'top-right',
): Point {
  if (placement === 'center') {
    const targetX = Math.round((bounds.width - size.width) / 2);
    const targetY = Math.round((bounds.height - size.height) / 2);
    return clampPosition({ x: targetX, y: targetY }, size, bounds, 0);
  }

  const top = offset?.top ?? 16;
  const right = offset?.right ?? 16;

  const targetX = bounds.width - size.width - right;
  const targetY = top;

  return clampPosition({ x: targetX, y: targetY }, size, bounds, 0);
}

export type ResizeHandle = 'n' | 's' | 'e' | 'w' | 'nw' | 'ne' | 'sw' | 'se';

export interface HandleResizeState {
  startPos: Point;
  startSize: Dimensions;
  handle: ResizeHandle;
}

export interface HandleResizeBounds {
  minWidth?: number;
  maxWidth?: number;
  minHeight?: number;
  maxHeight?: number;
  viewport?: Dimensions;
}

/**
 * Computes new dimensions and position based on drag delta for ANY of the 4 edges
 * ('n', 's', 'e', 'w') or 4 corners ('nw', 'ne', 'sw', 'se').
 */
export function computeHandleResize(
  state: HandleResizeState,
  deltaX: number,
  deltaY: number,
  bounds: HandleResizeBounds = {},
): { position: Point; size: Dimensions } {
  const minW = bounds.minWidth ?? 160;
  const maxW = bounds.maxWidth ?? (bounds.viewport?.width ?? Number.POSITIVE_INFINITY);
  const minH = bounds.minHeight ?? 100;
  const maxH = bounds.maxHeight ?? (bounds.viewport?.height ?? Number.POSITIVE_INFINITY);

  const vpW = bounds.viewport?.width ?? maxW;
  const vpH = bounds.viewport?.height ?? maxH;

  let newWidth = state.startSize.width;
  let newHeight = state.startSize.height;
  let newX = state.startPos.x;
  let newY = state.startPos.y;

  // Horizontal edge/corner resizing
  if (state.handle === 'e' || state.handle === 'se' || state.handle === 'ne') {
    const availableW = vpW - state.startPos.x;
    const effectiveMax = Math.min(maxW, Math.max(minW, availableW));
    newWidth = Math.round(Math.min(Math.max(state.startSize.width + deltaX, minW), effectiveMax));
  } else if (state.handle === 'w' || state.handle === 'sw' || state.handle === 'nw') {
    const rightEdge = state.startPos.x + state.startSize.width;
    const effectiveMax = Math.min(maxW, rightEdge);
    newWidth = Math.round(Math.min(Math.max(state.startSize.width - deltaX, minW), effectiveMax));
    newX = rightEdge - newWidth;
  }

  // Vertical edge/corner resizing
  if (state.handle === 's' || state.handle === 'se' || state.handle === 'sw') {
    const availableH = vpH - state.startPos.y;
    const effectiveMax = Math.min(maxH, Math.max(minH, availableH));
    newHeight = Math.round(Math.min(Math.max(state.startSize.height + deltaY, minH), effectiveMax));
  } else if (state.handle === 'n' || state.handle === 'ne' || state.handle === 'nw') {
    const bottomEdge = state.startPos.y + state.startSize.height;
    const effectiveMax = Math.min(maxH, bottomEdge);
    newHeight = Math.round(Math.min(Math.max(state.startSize.height - deltaY, minH), effectiveMax));
    newY = bottomEdge - newHeight;
  }

  return {
    position: { x: Math.max(0, newX), y: Math.max(0, newY) },
    size: { width: newWidth, height: newHeight },
  };
}
