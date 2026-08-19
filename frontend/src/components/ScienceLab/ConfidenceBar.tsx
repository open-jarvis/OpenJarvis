import { Gauge } from 'lucide-react';
import type { ScienceConfidence } from '../../lib/api';

export function ConfidenceBar({ confidence }: { confidence: ScienceConfidence }) {
  const pct = Math.round(Math.max(0, Math.min(1, confidence.value)) * 100);
  const color =
    pct >= 70 ? 'var(--color-success)' : pct >= 40 ? 'var(--color-warning)' : 'var(--color-error)';

  return (
    <div className="hud-panel p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="hud-label flex items-center gap-2">
          <Gauge size={12} style={{ color: 'var(--color-accent)' }} />
          CONFIDENCE
        </div>
        <span className="hud-mono text-sm font-semibold" style={{ color }}>
          {pct}%
        </span>
      </div>
      <div
        className="h-2 rounded-full overflow-hidden"
        style={{ background: 'var(--color-bg-tertiary)' }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: color, transition: 'width 0.4s ease' }}
        />
      </div>
      {confidence.basis && (
        <div className="text-xs mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
          Base: {confidence.basis}
        </div>
      )}
    </div>
  );
}
