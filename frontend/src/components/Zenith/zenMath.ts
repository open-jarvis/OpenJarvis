/** Small pure helpers for the home screen: charts, ring, quotes, greeting. */

export interface Point { x: number; y: number }

/** Points and a smooth-enough polyline path for 0..100 values in a w x h box. */
export function sparkline(values: number[], w: number, h: number, pad: number) {
  if (values.length === 0) return { points: [] as Point[], path: '' };
  const step = values.length > 1 ? (w - pad * 2) / (values.length - 1) : 0;
  const points = values.map((v, i) => ({
    x: Math.round(pad + i * step),
    y: Math.round(h - pad - (Math.max(0, Math.min(100, v)) / 100) * (h - pad * 2)),
  }));
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ');
  return { points, path };
}

/** ``stroke-dasharray`` that fills *percent* of a circle of radius *r*. */
export function ringDash(percent: number, r: number): string {
  const c = 2 * Math.PI * r;
  const filled = (c * Math.max(0, Math.min(100, percent))) / 100;
  return `${filled.toFixed(2)} ${c.toFixed(2)}`;
}

export type QuoteCategory = 'discipline' | 'success' | 'mindset' | 'life';
export interface Quote { text: string; category: QuoteCategory }

/** Original lines written for Jarvis. */
export const QUOTES: Quote[] = [
  { text: 'Quiet work today becomes loud results tomorrow.', category: 'discipline' },
  { text: 'Show up on the days you do not feel like it. Those days count double.', category: 'discipline' },
  { text: 'Small promises kept to yourself build the strongest trust.', category: 'discipline' },
  { text: 'Motivation starts the engine. Routine keeps it running.', category: 'discipline' },
  { text: 'Busy is a feeling. Progress is a fact. Choose the fact.', category: 'success' },
  { text: 'Build the habit first. The results will find their way to you.', category: 'success' },
  { text: 'One focused hour beats a distracted day.', category: 'success' },
  { text: 'Your future is assembled from what you repeat today.', category: 'success' },
  { text: 'The pressure you carry now is the strength you will stand on later.', category: 'mindset' },
  { text: 'Fall behind, then begin again. Starting over is still moving.', category: 'mindset' },
  { text: 'Calm mind, steady hands, clear target.', category: 'mindset' },
  { text: 'Doubt is loud, but it is not in charge.', category: 'mindset' },
  { text: 'Rest is part of the plan, not a break from it.', category: 'life' },
  { text: 'Protect your mornings and your evenings will thank you.', category: 'life' },
  { text: 'A good day is just a good hour repeated.', category: 'life' },
  { text: 'Keep going. Stop when the work is done, not when you are tired of it.', category: 'life' },
];

export const QUOTE_FILTERS: ('all' | QuoteCategory)[] = ['all', 'discipline', 'success', 'mindset', 'life'];

export function quotesFor(filter: 'all' | QuoteCategory): Quote[] {
  return filter === 'all' ? QUOTES : QUOTES.filter((q) => q.category === filter);
}

/** Same quote all day, a new one tomorrow. */
export function dailyQuote(now: Date = new Date()): Quote {
  const dayNumber = Math.floor(
    Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / 86_400_000,
  );
  return QUOTES[dayNumber % QUOTES.length];
}

export function greeting(now: Date = new Date()): string {
  const h = now.getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}
