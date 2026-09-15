import { describe, expect, it, vi } from 'vitest';
import {
  calculateDefaultPetPosition,
  calculateWanderStep,
  clampPetPosition,
  clearStoredPetPosition,
  clearStoredPetScale,
  DEFAULT_OFFSET_BOTTOM_VH,
  DEFAULT_OFFSET_RIGHT_VW,
  DEFAULT_PET_SIZE,
  DEFAULT_SAFE_MARGIN,
  DEFAULT_WANDER_INTERVAL_MS,
  DEFAULT_WANDER_MAX_STEP,
  DEFAULT_WANDER_MIN_STEP,
  PET_POSITION_STORAGE_KEY,
  PET_SCALE_STORAGE_KEY,
  persistPetPosition,
  persistPetScale,
  readStoredPetPosition,
  readStoredPetScale,
  useFloatingPet,
} from './useFloatingPet';
import type { PetPosition, PetSize } from '../components/Kiosk/Pet/types';

describe('useFloatingPet - Geometry & Positioning', () => {
  const defaultViewport: PetSize = { width: 1000, height: 800 };
  const petSize: PetSize = { width: 64, height: 64 };

  describe('calculateDefaultPetPosition', () => {
    it('calculates bottom-right position with default 6vw and 12vh offsets', () => {
      // 6vw of 1000 = 60px -> x = 1000 - 64 - 60 = 876
      // 12vh of 800 = 96px -> y = 800 - 64 - 96 = 640
      const pos = calculateDefaultPetPosition(defaultViewport, petSize);
      expect(pos).toEqual({ x: 876, y: 640 });
    });

    it('respects custom pixel offsets (rightPx, bottomPx)', () => {
      const pos = calculateDefaultPetPosition(defaultViewport, petSize, {
        rightPx: 40,
        bottomPx: 50,
      });
      // x = 1000 - 64 - 40 = 896
      // y = 800 - 64 - 50 = 686
      expect(pos).toEqual({ x: 896, y: 686 });
    });

    it('respects custom viewport ratio offsets (rightVw, bottomVh)', () => {
      const pos = calculateDefaultPetPosition(defaultViewport, petSize, {
        rightVw: 0.1, // 100px
        bottomVh: 0.2, // 160px
      });
      // x = 1000 - 64 - 100 = 836
      // y = 800 - 64 - 160 = 576
      expect(pos).toEqual({ x: 836, y: 576 });
    });

    it('clamps default position within viewport when viewport is small', () => {
      const smallViewport: PetSize = { width: 80, height: 80 };
      const pos = calculateDefaultPetPosition(smallViewport, petSize, undefined, 16);
      expect(pos.x).toBe(16);
      expect(pos.y).toBe(16);
    });

    it('handles negative or zero margins gracefully', () => {
      const pos = calculateDefaultPetPosition(defaultViewport, petSize, undefined, 0);
      expect(pos.x).toBe(876);
      expect(pos.y).toBe(640);
    });

    it('calculates centered position when placement is center', () => {
      // x = (1000 - 64) / 2 = 468, y = (800 - 64) / 2 = 368
      const pos = calculateDefaultPetPosition(defaultViewport, petSize, undefined, 16, 'center');
      expect(pos).toEqual({ x: 468, y: 368 });
    });
  });

  describe('clampPetPosition', () => {
    it('keeps position unchanged when comfortably inside bounds and margins', () => {
      const pos: PetPosition = { x: 400, y: 300 };
      const clamped = clampPetPosition(pos, petSize, defaultViewport, DEFAULT_SAFE_MARGIN);
      expect(clamped).toEqual({ x: 400, y: 300 });
    });

    it('clamps to left safe margin when x is too small', () => {
      const pos: PetPosition = { x: 5, y: 300 };
      const clamped = clampPetPosition(pos, petSize, defaultViewport, 16);
      expect(clamped).toEqual({ x: 16, y: 300 });
    });

    it('clamps to top safe margin when y is too small', () => {
      const pos: PetPosition = { x: 400, y: -20 };
      const clamped = clampPetPosition(pos, petSize, defaultViewport, 16);
      expect(clamped).toEqual({ x: 400, y: 16 });
    });

    it('clamps to right safe margin when x exceeds max allowed coordinate', () => {
      // maxX = 1000 - 64 - 16 = 920
      const pos: PetPosition = { x: 950, y: 300 };
      const clamped = clampPetPosition(pos, petSize, defaultViewport, 16);
      expect(clamped).toEqual({ x: 920, y: 300 });
    });

    it('clamps to bottom safe margin when y exceeds max allowed coordinate', () => {
      // maxY = 800 - 64 - 16 = 720
      const pos: PetPosition = { x: 400, y: 750 };
      const clamped = clampPetPosition(pos, petSize, defaultViewport, 16);
      expect(clamped).toEqual({ x: 400, y: 720 });
    });

    it('rounds decimal coordinates to whole integers', () => {
      const pos: PetPosition = { x: 400.7, y: 300.2 };
      const clamped = clampPetPosition(pos, petSize, defaultViewport, 16);
      expect(clamped).toEqual({ x: 401, y: 300 });
    });

    it('handles custom safe margin', () => {
      const pos: PetPosition = { x: 10, y: 10 };
      const clamped = clampPetPosition(pos, petSize, defaultViewport, 24);
      expect(clamped).toEqual({ x: 24, y: 24 });
    });

    it('handles tiny bounds by pinning to margin', () => {
      const tinyBounds: PetSize = { width: 50, height: 50 };
      const pos: PetPosition = { x: 30, y: 30 };
      const clamped = clampPetPosition(pos, petSize, tinyBounds, 10);
      expect(clamped).toEqual({ x: 10, y: 10 });
    });
  });
});

describe('useFloatingPet - Persistence', () => {
  it('reads stored position when valid JSON object is present', () => {
    const storage = {
      getItem: vi.fn(() => JSON.stringify({ x: 320, y: 480 })),
    };
    const result = readStoredPetPosition(storage);
    expect(result).toEqual({ x: 320, y: 480 });
    expect(storage.getItem).toHaveBeenCalledWith(PET_POSITION_STORAGE_KEY);
  });

  it('returns null when storage item is missing or null', () => {
    const storage = {
      getItem: vi.fn(() => null),
    };
    expect(readStoredPetPosition(storage)).toBeNull();
  });

  it('returns null when storage content is malformed or invalid structure', () => {
    expect(readStoredPetPosition({ getItem: () => 'invalid-json' })).toBeNull();
    expect(readStoredPetPosition({ getItem: () => JSON.stringify('string-value') })).toBeNull();
    expect(readStoredPetPosition({ getItem: () => JSON.stringify({ x: 100 }) })).toBeNull();
    expect(readStoredPetPosition({ getItem: () => JSON.stringify({ y: 100 }) })).toBeNull();
    expect(readStoredPetPosition({ getItem: () => JSON.stringify({ x: '100', y: '200' }) })).toBeNull();
    expect(readStoredPetPosition({ getItem: () => JSON.stringify({ x: Number.NaN, y: 200 }) })).toBeNull();
    expect(readStoredPetPosition({ getItem: () => JSON.stringify({ x: 100, y: Number.POSITIVE_INFINITY }) })).toBeNull();
  });

  it('persists rounded position under the storage key', () => {
    let savedKey = '';
    let savedVal = '';
    const storage = {
      setItem: vi.fn((key: string, val: string) => {
        savedKey = key;
        savedVal = val;
      }),
    };

    persistPetPosition({ x: 250.6, y: 399.1 }, storage);
    expect(savedKey).toBe(PET_POSITION_STORAGE_KEY);
    expect(JSON.parse(savedVal)).toEqual({ x: 251, y: 399 });
  });

  it('clears stored position from storage', () => {
    const storage = {
      removeItem: vi.fn(),
    };
    clearStoredPetPosition(storage);
    expect(storage.removeItem).toHaveBeenCalledWith(PET_POSITION_STORAGE_KEY);
  });

  describe('Scale Persistence', () => {
    it('reads stored scale when valid float string is present', () => {
      const storage = {
        getItem: vi.fn(() => '3.5'),
      };
      const result = readStoredPetScale(storage);
      expect(result).toBe(3.5);
      expect(storage.getItem).toHaveBeenCalledWith(PET_SCALE_STORAGE_KEY);
    });

    it('falls back to default scale when storage item is missing or out of bounds', () => {
      expect(readStoredPetScale({ getItem: () => null })).toBe(2);
      expect(readStoredPetScale({ getItem: () => 'invalid' })).toBe(2);
      expect(readStoredPetScale({ getItem: () => '0.5' })).toBe(2); // below minScale (1)
      expect(readStoredPetScale({ getItem: () => '10' })).toBe(2); // above maxScale (8)
    });

    it('persists rounded scale under the scale storage key', () => {
      let savedKey = '';
      let savedVal = '';
      const storage = {
        setItem: vi.fn((key: string, val: string) => {
          savedKey = key;
          savedVal = val;
        }),
      };

      persistPetScale(3.254, storage);
      expect(savedKey).toBe(PET_SCALE_STORAGE_KEY);
      expect(savedVal).toBe('3.25');
    });

    it('clears stored scale from storage', () => {
      const storage = {
        removeItem: vi.fn(),
      };
      clearStoredPetScale(storage);
      expect(storage.removeItem).toHaveBeenCalledWith(PET_SCALE_STORAGE_KEY);
    });
  });

  it('tolerates storage errors gracefully without throwing', () => {
    const throwingStorage = {
      getItem: () => {
        throw new Error('Access denied');
      },
      setItem: () => {
        throw new Error('Quota exceeded');
      },
      removeItem: () => {
        throw new Error('Access denied');
      },
    };

    expect(readStoredPetPosition(throwingStorage)).toBeNull();
    expect(() => persistPetPosition({ x: 100, y: 100 }, throwingStorage)).not.toThrow();
    expect(() => clearStoredPetPosition(throwingStorage)).not.toThrow();
  });
});

describe('useFloatingPet - Autonomous Wandering', () => {
  const viewport: PetSize = { width: 1000, height: 800 };
  const petSize: PetSize = { width: 64, height: 64 };
  const startPos: PetPosition = { x: 500, y: 500 };

  it('steps to the left when random direction is < 0.5', () => {
    // randomFn returns 0.2 (dir: -1, step: min + 0.2 * (max - min) = 10 + 0.2 * 15 = 13)
    const nextPos = calculateWanderStep(
      startPos,
      petSize,
      viewport,
      { min: 10, max: 25 },
      16,
      () => 0.2,
    );
    expect(nextPos.x).toBeLessThan(startPos.x);
    expect(nextPos.x).toBe(500 - 13);
  });

  it('steps to the right when random direction is >= 0.5', () => {
    // randomFn returns 0.8 (dir: +1, step: min + 0.8 * (max - min) = 10 + 0.8 * 15 = 22)
    const nextPos = calculateWanderStep(
      startPos,
      petSize,
      viewport,
      { min: 10, max: 25 },
      16,
      () => 0.8,
    );
    expect(nextPos.x).toBeGreaterThan(startPos.x);
    expect(nextPos.x).toBe(500 + 22);
  });

  it('clamps wander target so it never crosses safe viewport boundaries', () => {
    const nearRightEdge: PetPosition = { x: 915, y: 500 };
    // Stepping +25px right would reach 940, exceeding maxX of 1000 - 64 - 16 = 920
    const clampedPos = calculateWanderStep(
      nearRightEdge,
      petSize,
      viewport,
      { min: 20, max: 25 },
      16,
      () => 0.9,
    );
    expect(clampedPos.x).toBe(920);
  });

  it('handles custom step ranges', () => {
    const nextPos = calculateWanderStep(
      startPos,
      petSize,
      viewport,
      { min: 5, max: 10 },
      16,
      () => 0.6,
    );
    // dist = 5 + 0.6 * 5 = 8
    expect(nextPos.x).toBe(500 + 8);
  });
});

describe('useFloatingPet - Hook Signature & Defaults Exported', () => {
  it('exports expected constants', () => {
    expect(PET_POSITION_STORAGE_KEY).toBe('openjarvis_kiosk_pet_pos');
    expect(DEFAULT_PET_SIZE).toEqual({ width: 64, height: 64 });
    expect(DEFAULT_SAFE_MARGIN).toBe(16);
    expect(DEFAULT_OFFSET_RIGHT_VW).toBe(0.06);
    expect(DEFAULT_OFFSET_BOTTOM_VH).toBe(0.12);
    expect(DEFAULT_WANDER_INTERVAL_MS).toBe(10000);
    expect(DEFAULT_WANDER_MIN_STEP).toBe(10);
    expect(DEFAULT_WANDER_MAX_STEP).toBe(25);
  });

  it('provides a callable hook function', () => {
    expect(typeof useFloatingPet).toBe('function');
  });
});
