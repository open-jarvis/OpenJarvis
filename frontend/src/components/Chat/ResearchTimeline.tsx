import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { ResearchSearchTrace, TimeRange } from '../../types';

interface Props {
  traces: ResearchSearchTrace[];
  isLive: boolean;
  hasContent: boolean;
}

const SHORT_DATE = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
});

function fmtDate(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return SHORT_DATE.format(d);
}

function formatTimeRange(tr: TimeRange | string | undefined): string | null {
  if (!tr) return null;
  if (typeof tr === 'string') return tr.trim() || null;
  const start = tr.start ? fmtDate(tr.start) : null;
  const end = tr.end ? fmtDate(tr.end) : null;
  if (start && end) return start === end ? start : `${start} – ${end}`;
  if (start) return `after ${start}`;
  if (end) return `before ${end}`;
  return null;
}

function summarizeTraces(traces: ResearchSearchTrace[]): string {
  const n = traces.length;
  const hits = traces.reduce((s, t) => s + (t.numHits ?? 0), 0);
  const searchLabel = `${n} ${n === 1 ? 'search' : 'searches'}`;
  if (hits === 0) return searchLabel;
  return `${searchLabel} · ${hits} ${hits === 1 ? 'result' : 'results'}`;
}

function StatusLine({ text }: { text: string }) {
  return (
    <div
      className="text-xs leading-relaxed animate-pulse"
      style={{ color: 'var(--color-text-tertiary)' }}
    >
      {text}…
    </div>
  );
}

function TimelineStep({
  index,
  trace,
  isLive,
}: {
  index: number;
  trace: ResearchSearchTrace;
  isLive: boolean;
}) {
  const pending = trace.status === 'pending';
  const active = pending && isLive;
  const meta: string[] = [];
  if (trace.person) meta.push(`person: ${trace.person}`);
  const formattedTime = formatTimeRange(trace.timeRange);
  if (formattedTime) meta.push(`time: ${formattedTime}`);

  return (
    <div className="relative pl-4">
      {/* Step indicator dot, sitting on the vertical rail */}
      <div
        className="absolute left-0 top-[7px] w-1.5 h-1.5 rounded-full"
        style={{
          background: active
            ? 'var(--color-accent)'
            : 'var(--color-text-tertiary)',
          opacity: active ? 1 : 0.6,
          transform: 'translateX(-3px)',
          boxShadow: active ? '0 0 0 3px var(--color-accent-subtle)' : 'none',
          transition: 'background 200ms, box-shadow 200ms',
        }}
      />

      <div
        className="text-[10px] uppercase tracking-[0.08em] mb-0.5"
        style={{
          color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
        }}
      >
        Search {index}
      </div>

      <div
        className="text-sm"
        style={{ color: 'var(--color-text)', fontWeight: 450 }}
      >
        “{trace.query}”
      </div>

      {meta.length > 0 && (
        <div
          className="text-[11px] mt-0.5"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {meta.join(' · ')}
        </div>
      )}

      {active ? (
        <div
          className="mt-2 h-px overflow-hidden relative"
          style={{ background: 'var(--color-border)' }}
        >
          <div
            className="research-shimmer absolute inset-y-0 w-1/4"
            style={{ background: 'var(--color-accent)' }}
          />
        </div>
      ) : trace.numHits != null ? (
        <div
          className="text-[11px] mt-1"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {trace.numHits} {trace.numHits === 1 ? 'result' : 'results'}
        </div>
      ) : null}

      {trace.topTitles && trace.topTitles.length > 0 && (
        <div
          className="text-[11px] mt-0.5 truncate"
          style={{ color: 'var(--color-text-tertiary)', opacity: 0.75 }}
        >
          {trace.topTitles.slice(0, 2).join(' · ')}
        </div>
      )}
    </div>
  );
}

export function ResearchTimeline({ traces, isLive, hasContent }: Props) {
  const showAnalyzing = isLive && traces.length === 0 && !hasContent;
  const allComplete =
    traces.length > 0 && traces.every((t) => t.status === 'complete');
  const showSynthesizing = isLive && allComplete && !hasContent;

  // Auto-collapse the timeline the moment synthesis text begins streaming.
  // Subsequent user toggles win — we only fire the auto-collapse once per
  // false→true transition of hasContent.
  const [expanded, setExpanded] = useState(true);
  const prevHasContent = useRef(false);
  useEffect(() => {
    if (hasContent && !prevHasContent.current) {
      setExpanded(false);
    }
    prevHasContent.current = hasContent;
  }, [hasContent]);

  if (!showAnalyzing && traces.length === 0) return null;

  // No collapse affordance before any traces have arrived — just the
  // analyzing status sitting alone.
  if (traces.length === 0) {
    return (
      <div className="mb-4">
        <div className="relative pl-4">
          <div
            className="absolute left-0 top-[7px] w-1.5 h-1.5 rounded-full"
            style={{
              background: 'var(--color-accent)',
              transform: 'translateX(-3px)',
              boxShadow: '0 0 0 3px var(--color-accent-subtle)',
            }}
          />
          <StatusLine text="Analyzing query" />
        </div>
      </div>
    );
  }

  const summary = summarizeTraces(traces);
  const Chevron = expanded ? ChevronUp : ChevronDown;

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center gap-2 text-[11px] mb-2 cursor-pointer transition-colors"
        style={{
          color: 'var(--color-text-tertiary)',
          background: 'transparent',
          border: 'none',
          padding: 0,
        }}
        title={expanded ? 'Collapse search trace' : 'Expand search trace'}
      >
        <span>{summary}</span>
        <Chevron size={12} />
      </button>

      {expanded && (
        <div className="relative">
          <div
            aria-hidden
            className="absolute top-1 bottom-1 left-0 w-px"
            style={{ background: 'var(--color-border)' }}
          />
          <div className="flex flex-col gap-3">
            {traces.map((t, i) => (
              <TimelineStep
                key={t.id}
                index={i + 1}
                trace={t}
                isLive={isLive}
              />
            ))}

            {showSynthesizing && (
              <div className="relative pl-4">
                <div
                  className="absolute left-0 top-[7px] w-1.5 h-1.5 rounded-full"
                  style={{
                    background: 'var(--color-accent)',
                    transform: 'translateX(-3px)',
                    boxShadow: '0 0 0 3px var(--color-accent-subtle)',
                  }}
                />
                <StatusLine text="Synthesizing findings" />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
