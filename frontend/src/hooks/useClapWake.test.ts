import { describe, expect, it } from 'vitest';
import { isClapPeak } from './useClapWake';

describe('isClapPeak', () => {
  it('recognizes a sharp clap above the ambient-noise threshold', () => {
    expect(isClapPeak(0.04, 0.24)).toBe(true);
  });

  it('ignores steady background noise', () => {
    expect(isClapPeak(0.12, 0.18)).toBe(false);
  });

  it('ignores a small spike below the clap threshold', () => {
    expect(isClapPeak(0.02, 0.1)).toBe(false);
  });
});
