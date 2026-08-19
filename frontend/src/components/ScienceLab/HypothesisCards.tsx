import { Lightbulb, ThumbsUp, ThumbsDown } from 'lucide-react';
import type { ScienceHypothesis } from '../../lib/api';

export function HypothesisCards({ hypotheses }: { hypotheses: ScienceHypothesis[] }) {
  if (!hypotheses.length) return null;

  return (
    <div>
      <div className="hud-label mb-2 flex items-center gap-2">
        <Lightbulb size={12} style={{ color: 'var(--color-accent)' }} />
        HIPÓTESES
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {hypotheses.map((h) => (
          <div key={h.id} className="hud-panel p-4">
            <div className="hud-mono text-xs mb-1" style={{ color: 'var(--color-accent)' }}>
              {h.id}
            </div>
            <div className="text-sm font-medium mb-3" style={{ color: 'var(--color-text)' }}>
              {h.mechanism}
            </div>
            {Object.keys(h.key_properties).length > 0 && (
              <div className="mb-3 flex flex-col gap-1">
                {Object.entries(h.key_properties).map(([k, v]) => (
                  <div key={k} className="text-xs hud-mono" style={{ color: 'var(--color-text-secondary)' }}>
                    {k}: <span style={{ color: 'var(--color-text)' }}>{v}</span>
                  </div>
                ))}
              </div>
            )}
            {h.pros.length > 0 && (
              <div className="flex items-start gap-1.5 mb-1.5">
                <ThumbsUp size={12} className="shrink-0 mt-0.5" style={{ color: 'var(--color-success)' }} />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {h.pros.join('; ')}
                </span>
              </div>
            )}
            {h.cons.length > 0 && (
              <div className="flex items-start gap-1.5">
                <ThumbsDown size={12} className="shrink-0 mt-0.5" style={{ color: 'var(--color-warning)' }} />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {h.cons.join('; ')}
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
