import { describe, expect, it } from 'vitest';
import { dailyQuote, greeting, quotesFor, ringDash, sparkline } from './zenMath';

describe('sparkline', () => {
  it('maps 0..100 percents onto the chart box, top = 100%', () => {
    const { points } = sparkline([0, 50, 100], 200, 100, 10);
    expect(points[0]).toEqual({ x: 10, y: 90 });
    expect(points[1]).toEqual({ x: 100, y: 50 });
    expect(points[2]).toEqual({ x: 190, y: 10 });
  });

  it('builds an SVG path through every point', () => {
    const { path } = sparkline([20, 40], 100, 50, 0);
    expect(path.startsWith('M0,40')).toBe(true);
    expect(path).toContain('100,30');
  });

  it('handles an empty week', () => {
    expect(sparkline([], 100, 50, 0).path).toBe('');
  });
});

describe('ringDash', () => {
  it('turns a percent into stroke-dasharray for a circle', () => {
    const r = 10;
    const c = 2 * Math.PI * r;
    expect(ringDash(25, r)).toBe(`${(c * 0.25).toFixed(2)} ${c.toFixed(2)}`);
    expect(ringDash(150, r)).toBe(`${c.toFixed(2)} ${c.toFixed(2)}`);
    expect(ringDash(-5, r)).toBe(`0.00 ${c.toFixed(2)}`);
  });
});

describe('quotes', () => {
  it('filters by category and keeps all for ALL', () => {
    const all = quotesFor('all');
    expect(all.length).toBeGreaterThan(8);
    expect(quotesFor('discipline').every((q) => q.category === 'discipline')).toBe(true);
  });

  it('picks the same quote for the whole day', () => {
    const a = dailyQuote(new Date(2026, 10, 15, 8));
    const b = dailyQuote(new Date(2026, 10, 15, 22));
    const c = dailyQuote(new Date(2026, 10, 16, 8));
    expect(a).toEqual(b);
    expect(c).not.toEqual(a);
  });
});

describe('greeting', () => {
  it('follows the time of day', () => {
    expect(greeting(new Date(2026, 0, 1, 7))).toBe('Good morning');
    expect(greeting(new Date(2026, 0, 1, 14))).toBe('Good afternoon');
    expect(greeting(new Date(2026, 0, 1, 21))).toBe('Good evening');
  });
});
