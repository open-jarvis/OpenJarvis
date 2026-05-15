import { Loader2, Search } from 'lucide-react';
import type { ResearchSearchTrace } from '../../types';

interface Props {
  trace: ResearchSearchTrace;
}

export function ResearchTraceCard({ trace }: Props) {
  const pending = trace.status === 'pending';

  return (
    <div
      className="rounded-md px-2.5 py-1.5 text-xs flex items-center gap-2"
      style={{
        border: '1px solid var(--color-border-subtle, var(--color-border))',
        background: 'var(--color-bg-tertiary, var(--color-bg-secondary))',
        color: 'var(--color-text-secondary)',
      }}
    >
      {pending ? (
        <Loader2
          size={11}
          className="animate-spin"
          style={{ color: 'var(--color-accent)', flexShrink: 0 }}
        />
      ) : (
        <Search
          size={11}
          style={{ color: 'var(--color-accent)', flexShrink: 0 }}
        />
      )}
      <span style={{ color: 'var(--color-text-tertiary)', flexShrink: 0 }}>
        Searching:
      </span>
      <span
        className="truncate"
        style={{ color: 'var(--color-text-secondary)', fontWeight: 500 }}
      >
        “{trace.query}”
      </span>
      {trace.person && (
        <span
          className="truncate"
          style={{ color: 'var(--color-text-tertiary)', fontSize: 10.5 }}
        >
          (person: {trace.person})
        </span>
      )}
      <div className="flex-1" />
      {trace.numHits != null && (
        <span
          style={{
            color: 'var(--color-text-tertiary)',
            fontSize: 10.5,
            flexShrink: 0,
          }}
        >
          → {trace.numHits} hits
        </span>
      )}
    </div>
  );
}
