import { describe, expect, it } from 'vitest';
import { MIN_SAMPLES_FOR_VERDICT, blockPeak, isDigitalSilence } from './mic-level';

const meter = (peak: number, samples: number) => ({ peak: () => peak, samples: () => samples });

describe('blockPeak', () => {
  it('returns the largest absolute sample', () => {
    expect(blockPeak([0, 0.2, -0.5, 0.1])).toBe(0.5);
  });

  it('is zero for an all-zero block', () => {
    expect(blockPeak(new Float32Array(16))).toBe(0);
  });
});

describe('isDigitalSilence', () => {
  it('flags a recording whose every sample was exactly zero', () => {
    expect(isDigitalSilence(meter(0, 30))).toBe(true);
  });

  it('does not flag a quiet room (a real mic always has a noise floor)', () => {
    expect(isDigitalSilence(meter(0.0004, 30))).toBe(false);
  });

  it('does not judge a recording too short to have been sampled', () => {
    expect(isDigitalSilence(meter(0, MIN_SAMPLES_FOR_VERDICT - 1))).toBe(false);
  });

  it('skips the check when no meter could be created', () => {
    expect(isDigitalSilence(null)).toBe(false);
  });
});
