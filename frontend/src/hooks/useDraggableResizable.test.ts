import { describe, expect, it } from 'vitest';
import {
  useDraggableResizable,
  getViewportBounds,
  getMaxWidthForViewport,
} from './useDraggableResizable';

describe('useDraggableResizable - Viewport & Sizing Calculations', () => {
  describe('viewport calculations', () => {
    it('returns default fallback bounds when window is undefined', () => {
      expect(getViewportBounds(undefined)).toEqual({ width: 1920, height: 1080 });
    });

    it('returns custom window dimensions from getViewportBounds', () => {
      const mockWin = { innerWidth: 1920, innerHeight: 1080 };
      expect(getViewportBounds(mockWin)).toEqual({ width: 1920, height: 1080 });
    });

    it('calculates maximum width that fits full viewport at 16:9 ratio without capping at 1000px', () => {
      // For 1920x1080 at 16:9: Math.min(1920, 1080 * 16 / 9) = 1920
      const mockWin = { innerWidth: 1920, innerHeight: 1080 };
      const maxWidth = getMaxWidthForViewport(16 / 9, mockWin);
      expect(maxWidth).toBe(1920);
      expect(maxWidth).toBeGreaterThan(1000);
    });

    it('calculates full width on 4K display', () => {
      const mockWin = { innerWidth: 3840, innerHeight: 2160 };
      const maxWidth = getMaxWidthForViewport(16 / 9, mockWin);
      expect(maxWidth).toBe(3840);
    });

    it('limits width if screen height would be exceeded on ultrawide display', () => {
      // 3440x1440: at 16:9, max height is 1440 -> max width is 1440 * 16 / 9 = 2560
      const mockWin = { innerWidth: 3440, innerHeight: 1440 };
      const maxWidth = getMaxWidthForViewport(16 / 9, mockWin);
      expect(maxWidth).toBe(2560);
    });

    it('allows full ultrawide width when stream aspect ratio matches ultrawide (21:9)', () => {
      const mockWin = { innerWidth: 3440, innerHeight: 1440 };
      const maxWidth = getMaxWidthForViewport(21 / 9, mockWin);
      expect(maxWidth).toBe(3360);
    });
  });

  describe('hook exports', () => {
    it('provides a callable hook function', () => {
      expect(typeof useDraggableResizable).toBe('function');
    });
  });
});
