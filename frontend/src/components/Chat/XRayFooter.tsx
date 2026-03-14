import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { TokenUsage, MessageTelemetry } from '../../types';

interface Props {
  usage?: TokenUsage;
  telemetry?: MessageTelemetry;
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function XRayFooter({ usage, telemetry }: Props) {
  const [expanded, setExpanded] = useState(false);

  // Build collapsed summary parts
  const parts: string[] = [];
  if (telemetry?.engine) parts.push(telemetry.engine);
  if (telemetry?.model_id) parts.push(telemetry.model_id);
  if (usage && (usage.prompt_tokens || usage.completion_tokens)) {
    parts.push(`${usage.prompt_tokens} in \u00B7 ${usage.completion_tokens} out`);
  }
  if (telemetry?.total_ms) parts.push(formatMs(telemetry.total_ms));

  if (parts.length === 0 && !usage?.total_tokens) return null;

  // Fallback: just show total tokens if no telemetry
  const summary = parts.length > 0 ? parts.join(' \u00B7 ') : `${usage!.total_tokens} tokens`;

  // Build expanded rows
  const rows: Array<{ label: string; value: string; color?: string }> = [];
  if (telemetry?.engine) {
    const modelDetail = telemetry.model_id || '';
    rows.push({ label: 'Engine', value: `${telemetry.engine}${modelDetail ? ` (${modelDetail})` : ''}` });
  }
  if (usage) {
    rows.push({ label: 'Tokens', value: `${usage.completion_tokens} generated \u00B7 ${usage.prompt_tokens} prompt` });
  }
  if (telemetry?.tokens_per_sec) {
    rows.push({ label: 'Speed', value: `${Math.round(telemetry.tokens_per_sec)} tok/s` });
  }
  if (telemetry?.ttft_ms != null || telemetry?.total_ms != null) {
    const latencyParts: string[] = [];
    if (telemetry.ttft_ms != null) latencyParts.push(`TTFT ${formatMs(telemetry.ttft_ms)}`);
    if (telemetry.total_ms != null) latencyParts.push(`Total ${formatMs(telemetry.total_ms)}`);
    rows.push({ label: 'Latency', value: latencyParts.join(' \u00B7 ') });
  }

  return (
    <div style={{ borderTop: '1px solid var(--color-border-subtle)', marginTop: '0.375rem' }}>
      {/* Collapsed row */}
      <button
        onClick={() => rows.length > 0 && setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left py-1"
        style={{ cursor: rows.length > 0 ? 'pointer' : 'default' }}
      >
        <span
          className="w-1 h-1 rounded-full shrink-0"
          style={{ background: 'var(--color-accent)' }}
        />
        <span
          className="text-[11px] flex-1"
          style={{ color: 'var(--color-text-tertiary)', fontFamily: 'system-ui' }}
        >
          {summary}
        </span>
        {rows.length > 0 && (
          expanded
            ? <ChevronUp size={10} style={{ color: 'var(--color-text-tertiary)' }} />
            : <ChevronDown size={10} style={{ color: 'var(--color-text-tertiary)' }} />
        )}
      </button>

      {/* Expanded trace */}
      {expanded && rows.length > 0 && (
        <div
          className="rounded-lg mt-1 px-3 py-2"
          style={{ background: 'rgba(0, 0, 0, 0.15)' }}
        >
          <div className="grid gap-y-0.5" style={{ gridTemplateColumns: 'auto 1fr', columnGap: '1rem' }}>
            {rows.map((row) => (
              <div key={row.label} className="contents">
                <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)', fontFamily: 'monospace' }}>
                  {row.label}
                </span>
                <span
                  className="text-[11px]"
                  style={{ color: row.color || 'var(--color-text-secondary)', fontFamily: 'monospace' }}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
