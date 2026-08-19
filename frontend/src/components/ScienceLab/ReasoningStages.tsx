import { useEffect, useState } from 'react';
import { CheckCircle2 } from 'lucide-react';

// Fixed 7-stage reasoning pipeline, matching ScienceLabAgent's
// reasoning_summary order exactly.
const STAGE_LABELS = [
  'OBJETIVO',
  'PROPRIEDADES',
  'CANDIDATOS',
  'MODELO',
  'SIMULAÇÃO',
  'RESULTADO',
  'LIMITAÇÕES',
] as const;

const PHASE_TEXT: Record<string, string> = {
  OBJETIVO: 'INITIALIZING...',
  PROPRIEDADES: 'ANALYZING PROPERTIES...',
  CANDIDATOS: 'GENERATING HYPOTHESES...',
  MODELO: 'SELECTING MODEL...',
  SIMULAÇÃO: 'RUNNING SIMULATION...',
  RESULTADO: 'SYNTHESIZING RESULT...',
  LIMITAÇÕES: 'FINALIZING...',
};

interface ReasoningStagesProps {
  loading: boolean;
  stages: [string, string][] | null;
}

function StageRow({
  label,
  text,
  state,
}: {
  label: string;
  text?: string;
  state: 'done' | 'active' | 'pending';
}) {
  return (
    <div
      className="flex items-start gap-3 px-3 py-2.5 rounded-lg transition-all"
      style={{
        background: state === 'active' ? 'var(--color-accent-subtle)' : 'transparent',
      }}
    >
      <div className="shrink-0 mt-0.5">
        {state === 'done' ? (
          <CheckCircle2 size={14} style={{ color: 'var(--color-accent)' }} />
        ) : state === 'active' ? (
          <span className="hud-reticle" style={{ width: 14, height: 14 }} />
        ) : (
          <div
            className="w-3.5 h-3.5 rounded-full"
            style={{ border: '1.5px solid var(--color-border)' }}
          />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="hud-label" style={{ color: state === 'pending' ? 'var(--color-text-tertiary)' : 'var(--color-accent)' }}>
          {label}
        </div>
        {text && (
          <div className="text-sm mt-1 whitespace-pre-wrap hud-mono" style={{ color: 'var(--color-text-secondary)' }}>
            {text}
          </div>
        )}
      </div>
    </div>
  );
}

export function ReasoningStages({ loading, stages }: ReasoningStagesProps) {
  const [animatedIndex, setAnimatedIndex] = useState(0);

  useEffect(() => {
    if (!loading) {
      setAnimatedIndex(0);
      return;
    }
    const interval = setInterval(() => {
      setAnimatedIndex((i) => (i + 1) % STAGE_LABELS.length);
    }, 900);
    return () => clearInterval(interval);
  }, [loading]);

  if (!loading && !stages) return null;

  const stageMap = new Map(stages ?? []);
  const headerText = loading
    ? PHASE_TEXT[STAGE_LABELS[animatedIndex]]
    : 'ANALYSIS COMPLETE';

  return (
    <div className="hud-panel p-5">
      <div className="flex items-center gap-2 mb-4">
        <span className="hud-heartbeat" />
        <span className="hud-title hud-mono text-xs" style={{ color: 'var(--color-accent)', letterSpacing: '0.1em' }}>
          J.A.R.V.I.S. SCIENCE LAB
        </span>
        <span className="hud-mono text-xs ml-auto" style={{ color: 'var(--color-text-tertiary)' }}>
          {headerText}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        {STAGE_LABELS.map((label, idx) => {
          const done = stages !== null && stageMap.has(label);
          const active = loading && idx === animatedIndex;
          const state: 'done' | 'active' | 'pending' = done ? 'done' : active ? 'active' : 'pending';
          return (
            <StageRow key={label} label={label} text={stageMap.get(label)} state={state} />
          );
        })}
      </div>
    </div>
  );
}
