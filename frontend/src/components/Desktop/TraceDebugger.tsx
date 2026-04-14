import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import { invoke } from '@tauri-apps/api/core';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TraceStepData {
  model?: string;
  tokens?: number;
  tool?: string;
  input?: string;
  output?: string;
  backend?: string;
  results?: number;
  policy?: string;
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

interface TraceListResponse {
  traces: TraceSummary[];
}

interface TraceDetail {
  id: string;
  query: string;
  steps: TraceStep[];
  created_at?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEP_COLORS: Record<string, string> = {
  route: '#89b4fa',
  retrieve: '#a6e3a1',
  generate: '#f9e2af',
  tool_call: '#cba6f7',
  respond: '#f38ba8',
};

const DEFAULT_STEP_COLOR = '#9399b2';

const colors = {
  bg: '#1e1e2e',
  surface: '#282840',
  surfaceHover: '#313150',
  text: '#cdd6f4',
  textMuted: '#a6adc8',
  accent: '#89b4fa',
  border: '#45475a',
  red: '#f38ba8',
} as const;

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: colors.bg,
    color: colors.text,
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    display: 'flex',
    height: '100%',
    boxSizing: 'border-box',
  },

  // Left panel - trace list
  listPanel: {
    width: 320,
    minWidth: 280,
    borderRight: `1px solid ${colors.border}`,
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  listHeader: {
    padding: '20px 16px 12px',
    borderBottom: `1px solid ${colors.border}`,
    flexShrink: 0,
  },
  listTitle: {
    fontSize: 18,
    fontWeight: 600,
    margin: 0,
    marginBottom: 4,
    color: colors.text,
  },
  listSubtitle: {
    fontSize: 12,
    color: colors.textMuted,
    margin: 0,
  },
  listScroll: {
    flex: 1,
    overflowY: 'auto',
    padding: '8px 0',
  },
  traceItem: {
    padding: '10px 16px',
    cursor: 'pointer',
    borderBottom: `1px solid ${colors.border}`,
    transition: 'background 0.15s',
  },
  traceItemSelected: {
    background: colors.surfaceHover,
  },
  traceItemId: {
    fontSize: 13,
    fontWeight: 600,
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    color: colors.accent,
    marginBottom: 3,
  },
  traceItemQuery: {
    fontSize: 12,
    color: colors.text,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    marginBottom: 3,
    maxWidth: '100%',
  },
  traceItemMeta: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 11,
    color: colors.textMuted,
  },

  // Right panel - detail
  detailPanel: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  detailHeader: {
    padding: '20px 24px 16px',
    borderBottom: `1px solid ${colors.border}`,
    flexShrink: 0,
  },
  detailTitle: {
    fontSize: 16,
    fontWeight: 600,
    margin: 0,
    marginBottom: 4,
    color: colors.text,
  },
  detailQuery: {
    fontSize: 13,
    color: colors.textMuted,
    margin: 0,
    marginBottom: 8,
    lineHeight: 1.4,
  },
  detailStats: {
    display: 'flex',
    gap: 16,
    fontSize: 12,
    color: colors.textMuted,
  },
  detailStatValue: {
    fontWeight: 600,
    color: colors.accent,
  },
  detailScroll: {
    flex: 1,
    overflowY: 'auto',
    padding: 24,
  },
  timelineContainer: {
    position: 'relative',
    paddingLeft: 24,
  },
  timelineLine: {
    position: 'absolute',
    left: 7,
    top: 0,
    bottom: 0,
    width: 2,
    background: colors.border,
  },

  // Timeline step
  stepContainer: {
    position: 'relative',
    marginBottom: 16,
  },
  stepDot: {
    position: 'absolute',
    left: -20,
    top: 8,
    width: 12,
    height: 12,
    borderRadius: '50%',
    border: `2px solid ${colors.bg}`,
  },
  stepCard: {
    background: colors.surface,
    borderRadius: 8,
    padding: 14,
    border: `1px solid ${colors.border}`,
  },
  stepHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  stepBadge: {
    display: 'inline-block',
    padding: '2px 10px',
    borderRadius: 10,
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
  },
  stepDuration: {
    fontSize: 12,
    color: colors.textMuted,
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
  },
  stepDetails: {
    fontSize: 12,
    color: colors.textMuted,
    lineHeight: 1.6,
  },
  stepDetailRow: {
    display: 'flex',
    gap: 8,
  },
  stepDetailKey: {
    color: colors.textMuted,
    minWidth: 60,
    flexShrink: 0,
  },
  stepDetailValue: {
    color: colors.text,
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    fontSize: 11,
    wordBreak: 'break-all',
  },
  expandButton: {
    background: 'none',
    border: 'none',
    color: colors.accent,
    fontSize: 11,
    cursor: 'pointer',
    padding: '4px 0',
    textAlign: 'left',
  },

  // Empty state
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: colors.textMuted,
    gap: 12,
    padding: 32,
  },
  emptyIcon: {
    fontSize: 40,
    opacity: 0.4,
  },
  emptyText: {
    fontSize: 15,
    textAlign: 'center',
  },
  errorBanner: {
    background: 'rgba(243,139,168,0.1)',
    border: `1px solid ${colors.red}`,
    borderRadius: 8,
    padding: '10px 16px',
    margin: 16,
    fontSize: 13,
    color: colors.red,
  },
  placeholder: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: colors.textMuted,
    fontSize: 14,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function truncateId(id: string, len: number = 12): string {
  if (id.length <= len) return id;
  return id.slice(0, len) + '...';
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return ts;
  }
}

function formatDuration(ms: number): string {
  if (ms < 1) return '<1ms';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function stepColor(stepType: string): string {
  return STEP_COLORS[stepType] ?? DEFAULT_STEP_COLOR;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StepDataView({ data }: { data: TraceStepData }) {
  const [expanded, setExpanded] = useState(false);

  const entries = Object.entries(data).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  );

  if (entries.length === 0) {
    return null;
  }

  // Show up to 3 entries by default; expand to show all
  const displayEntries = expanded ? entries : entries.slice(0, 3);
  const hasMore = entries.length > 3;

  return (
    <div style={styles.stepDetails}>
      {displayEntries.map(([key, value]) => (
        <div key={key} style={styles.stepDetailRow}>
          <span style={styles.stepDetailKey}>{key}:</span>
          <span style={styles.stepDetailValue}>
            {typeof value === 'object' ? JSON.stringify(value) : String(value)}
          </span>
        </div>
      ))}
      {hasMore && (
        <button
          style={styles.expandButton}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Show less' : `Show ${entries.length - 3} more fields...`}
        </button>
      )}
    </div>
  );
}

interface TimelineStepProps {
  step: TraceStep;
}

function TimelineStep({ step }: TimelineStepProps) {
  const color = stepColor(step.step_type);

  return (
    <div style={styles.stepContainer}>
      <div style={{ ...styles.stepDot, background: color }} />
      <div style={styles.stepCard}>
        <div style={styles.stepHeader}>
          <span
            style={{
              ...styles.stepBadge,
              background: `${color}22`,
              color,
            }}
          >
            {step.step_type}
          </span>
          <span style={styles.stepDuration}>{formatDuration(step.duration_ms)}</span>
        </div>
        {step.data && <StepDataView data={step.data} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function TraceDebugger({ apiUrl }: { apiUrl: string }) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);

  // Fetch trace list
  const fetchTraces = useCallback(async () => {
    try {
      const response = await invoke<TraceListResponse>('fetch_traces', {
        apiUrl,
        limit: 50,
      });
      setTraces(response.traces ?? []);
      setError(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setTraces([]);
    } finally {
      setListLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]);

  // Fetch trace detail when selection changes
  const fetchDetail = useCallback(
    async (traceId: string) => {
      setDetailLoading(true);
      try {
        const detail = await invoke<TraceDetail>('fetch_trace', {
          apiUrl,
          traceId,
        });
        setTraceDetail(detail);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setTraceDetail(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [apiUrl],
  );

  const handleSelectTrace = useCallback(
    (traceId: string) => {
      setSelectedId(traceId);
      fetchDetail(traceId);
    },
    [fetchDetail],
  );

  // Compute totals for detail header
  const totalDuration =
    traceDetail?.steps.reduce((sum, s) => sum + s.duration_ms, 0) ?? 0;

  // --- Empty state ---
  if (!listLoading && traces.length === 0 && !error) {
    return (
      <div style={styles.container}>
        <div style={styles.emptyState}>
          <div style={styles.emptyIcon}>&#x1F50D;</div>
          <div style={styles.emptyText}>
            No traces available.<br />
            Traces are recorded when queries are processed through the system.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Left panel - trace list */}
      <div style={styles.listPanel}>
        <div style={styles.listHeader}>
          <h2 style={styles.listTitle}>Traces</h2>
          <p style={styles.listSubtitle}>{traces.length} recent traces</p>
        </div>

        {error && <div style={styles.errorBanner}>{error}</div>}

        <div style={styles.listScroll}>
          {traces.map((trace) => {
            const isSelected = trace.id === selectedId;
            return (
              <div
                key={trace.id}
                style={{
                  ...styles.traceItem,
                  ...(isSelected ? styles.traceItemSelected : {}),
                }}
                onClick={() => handleSelectTrace(trace.id)}
                onMouseEnter={(e) => {
                  if (!isSelected) {
                    (e.currentTarget as HTMLDivElement).style.background =
                      colors.surfaceHover;
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) {
                    (e.currentTarget as HTMLDivElement).style.background = '';
                  }
                }}
              >
                <div style={styles.traceItemId}>{truncateId(trace.id)}</div>
                <div style={styles.traceItemQuery}>{trace.query}</div>
                <div style={styles.traceItemMeta}>
                  <span>{trace.steps.length} steps</span>
                  <span>{formatTimestamp(trace.created_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right panel - trace detail */}
      <div style={styles.detailPanel}>
        {!selectedId && (
          <div style={styles.placeholder}>
            Select a trace from the list to inspect its steps.
          </div>
        )}

        {selectedId && detailLoading && (
          <div style={styles.placeholder}>Loading trace...</div>
        )}

        {selectedId && !detailLoading && traceDetail && (
          <>
            <div style={styles.detailHeader}>
              <h3 style={styles.detailTitle}>
                Trace {truncateId(traceDetail.id)}
              </h3>
              <p style={styles.detailQuery}>
                Query: &quot;{traceDetail.query}&quot;
              </p>
              <div style={styles.detailStats}>
                <span>
                  Steps:{' '}
                  <span style={styles.detailStatValue}>
                    {traceDetail.steps.length}
                  </span>
                </span>
                <span>
                  Total:{' '}
                  <span style={styles.detailStatValue}>
                    {formatDuration(totalDuration)}
                  </span>
                </span>
                {traceDetail.created_at && (
                  <span>
                    Created:{' '}
                    <span style={styles.detailStatValue}>
                      {formatTimestamp(traceDetail.created_at)}
                    </span>
                  </span>
                )}
              </div>
            </div>

            <div style={styles.detailScroll}>
              {traceDetail.steps.length === 0 ? (
                <div style={styles.placeholder}>
                  This trace contains no steps.
                </div>
              ) : (
                <div style={styles.timelineContainer}>
                  <div style={styles.timelineLine} />
                  {traceDetail.steps.map((step, idx) => (
                    <TimelineStep key={idx} step={step} />
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
