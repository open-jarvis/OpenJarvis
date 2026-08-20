import { useState, useEffect, useCallback } from 'react';
import { GitBranch, Clock, ChevronRight, ChevronDown } from 'lucide-react';

interface TraceStepData {
  model?: string;
  tokens?: number;
  tool?: string;
  input?: string;
  output?: string;
  [key: string]: unknown;
}

interface TraceStep {
  step_type: string;
  duration_ms: number;
  data: TraceStepData;
}

interface TraceSummary {
  id: string;
  query: string;
  steps: TraceStep[];
  created_at: string;
}

const STEP_COLORS: Record<string, string> = {
  route: 'var(--color-accent)',
  retrieve: 'var(--color-success)',
  generate: 'var(--color-warning)',
  tool_call: 'var(--color-accent-purple)',
  respond: 'var(--color-accent-purple)',
};

function StepBadge({ type }: { type: string }) {
  const color = STEP_COLORS[type] || 'var(--color-text-tertiary)';
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{ background: `color-mix(in srgb, ${color} 15%, transparent)`, color }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {type}
    </span>
  );
}

function TraceCard({ trace, isActive, onClick }: { trace: TraceSummary; isActive: boolean; onClick: () => void }) {
  const totalMs = trace.steps.reduce((sum, s) => sum + s.duration_ms, 0);

  return (
    <button
      onClick={onClick}
      className="w-full text-left p-3 rounded-lg transition-colors cursor-pointer"
      style={{
        background: isActive ? 'var(--color-bg-tertiary)' : 'transparent',
        border: isActive ? '1px solid var(--color-border)' : '1px solid transparent',
      }}
      onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)'; }}
      onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
    >
      <div className="text-sm truncate mb-1" style={{ color: 'var(--color-text)' }}>
        {trace.query || 'Untitled query'}
      </div>
      <div className="flex items-center gap-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>{trace.steps.length} steps</span>
        <span>&middot;</span>
        <span>{totalMs.toFixed(0)}ms</span>
        <span>&middot;</span>
        <span>{new Date(trace.created_at).toLocaleTimeString()}</span>
      </div>
    </button>
  );
}

function StepDetail({ step, index }: { step: TraceStep; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const dataEntries = Object.entries(step.data).filter(([_, v]) => v != null);

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ border: '1px solid var(--color-border)' }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-3 py-2 text-sm transition-colors cursor-pointer"
        style={{ background: 'var(--color-bg-secondary)' }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="text-xs font-mono" style={{ color: 'var(--color-text-tertiary)' }}>
          {index + 1}
        </span>
        <StepBadge type={step.step_type} />
        <span className="flex-1" />
        <span className="text-xs font-mono flex items-center gap-1" style={{ color: 'var(--color-text-tertiary)' }}>
          <Clock size={10} />
          {step.duration_ms.toFixed(0)}ms
        </span>
      </button>
      {expanded && dataEntries.length > 0 && (
        <div className="px-3 py-2 text-xs" style={{ borderTop: '1px solid var(--color-border)' }}>
          {dataEntries.map(([key, value]) => (
            <div key={key} className="flex gap-2 py-1">
              <span className="font-mono shrink-0" style={{ color: 'var(--color-text-tertiary)', minWidth: '80px' }}>
                {key}
              </span>
              <span className="truncate" style={{ color: 'var(--color-text-secondary)' }}>
                {typeof value === 'object' ? JSON.stringify(value) : String(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function TraceDebugger() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchTraces = useCallback(async () => {
    try {
      const base = import.meta.env.VITE_API_URL || '';
      const res = await fetch(`${base}/v1/traces?limit=50`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTraces(data.traces || []);
      setError(null);
    } catch {
      setError('Cannot load traces');
    }
  }, []);

  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]);

  const selected = traces.find((t) => t.id === selectedId);

  if (error) {
    return (
      <div className="hud-panel p-6">
        <h3 className="hud-label flex items-center gap-2 mb-4">
          <GitBranch size={12} style={{ color: 'var(--color-accent)' }} />
          Trace Debugger
        </h3>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span className="hud-mono">{error}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="hud-panel p-6">
      <h3 className="hud-label flex items-center gap-2 mb-4">
        <GitBranch size={12} style={{ color: 'var(--color-accent)' }} />
        Trace Debugger
      </h3>

      {traces.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          No traces yet. Start making queries to see them here.
        </div>
      ) : (
        <div className="flex gap-4 h-80">
          {/* Trace list */}
          <div className="w-1/3 overflow-y-auto flex flex-col gap-1 pr-2" style={{ borderRight: '1px solid var(--color-border)' }}>
            {traces.map((trace) => (
              <TraceCard
                key={trace.id}
                trace={trace}
                isActive={trace.id === selectedId}
                onClick={() => setSelectedId(trace.id)}
              />
            ))}
          </div>

          {/* Trace detail */}
          <div className="flex-1 overflow-y-auto">
            {selected ? (
              <div className="flex flex-col gap-2">
                <div className="text-sm font-medium mb-2" style={{ color: 'var(--color-text)' }}>
                  {selected.query}
                </div>
                {selected.steps.map((step, i) => (
                  <StepDetail key={i} step={step} index={i} />
                ))}
              </div>
            ) : (
              <div className="h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Select a trace to view details
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
