import React, { useState, useEffect, useCallback } from 'react';
import { Shield, Loader2, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import { fetchAlerts, type AlertsResponse } from '../Desktop/lib/api';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

interface AlertItem {
  id: string;
  target: string;
  type: string;
  timestamp: string;
  metadata: {
    diff?: {
      changed?: Record<string, unknown>;
      added?: Record<string, unknown>;
      removed?: Record<string, unknown>;
    };
  };
}

export function AlertsPanel() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data: AlertsResponse = await fetchAlerts(API_URL, 50);
      setAlerts(data.alerts as AlertItem[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const formatDiff = (diff: AlertItem['metadata']['diff']) => {
    if (!diff) return null;
    const sections: React.ReactNode[] = [];

    if (diff.changed && Object.keys(diff.changed).length > 0) {
      sections.push(
        <div key="changed" className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-warning)' }}>
            Changed
          </span>
          {Object.entries(diff.changed).map(([key, value]) => (
            <div
              key={key}
              className="rounded-md px-2 py-1 text-xs"
              style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
            >
              <span style={{ color: 'var(--color-text-secondary)' }}>{key}:</span>{' '}
              <span style={{ color: 'var(--color-text)' }}>
                {typeof value === 'object' && value !== null
                  ? JSON.stringify(value)
                  : String(value)}
              </span>
            </div>
          ))}
        </div>,
      );
    }

    if (diff.added && Object.keys(diff.added).length > 0) {
      sections.push(
        <div key="added" className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-success)' }}>
            Added
          </span>
          {Object.entries(diff.added).map(([key, value]) => (
            <div
              key={key}
              className="rounded-md px-2 py-1 text-xs"
              style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
            >
              <span style={{ color: 'var(--color-text-secondary)' }}>{key}:</span>{' '}
              <span style={{ color: 'var(--color-text)' }}>
                {Array.isArray(value) ? value.join(', ') : String(value)}
              </span>
            </div>
          ))}
        </div>,
      );
    }

    if (diff.removed && Object.keys(diff.removed).length > 0) {
      sections.push(
        <div key="removed" className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-error)' }}>
            Removed
          </span>
          {Object.entries(diff.removed).map(([key, value]) => (
            <div
              key={key}
              className="rounded-md px-2 py-1 text-xs"
              style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
            >
              <span style={{ color: 'var(--color-text-secondary)' }}>{key}:</span>{' '}
              <span style={{ color: 'var(--color-text)' }}>
                {Array.isArray(value) ? value.join(', ') : String(value)}
              </span>
            </div>
          ))}
        </div>,
      );
    }

    return sections;
  };

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={16} style={{ color: 'var(--color-accent)' }} />
          <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            Change Alerts
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text-tertiary)',
              border: '1px solid var(--color-border)',
            }}
          >
            {alerts.length}
          </span>
        </div>
      </div>

      {error && (
        <div
          className="px-4 py-3 rounded-lg text-sm flex items-center gap-2"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-error)',
          }}
        >
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-xs py-8 justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
          <Loader2 size={14} className="animate-spin" />
          Loading...
        </div>
      )}

      {!loading && alerts.length === 0 && (
        <div
          className="rounded-lg p-8 text-center text-sm"
          style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}
        >
          <Shield size={24} className="mx-auto mb-2 opacity-50" />
          No change alerts yet. Alerts appear when scheduled scans detect differences.
        </div>
      )}

      <div className="flex flex-col gap-2">
        {alerts.map((alert) => {
          const isExpanded = expandedId === alert.id;
          const diff = alert.metadata?.diff;
          const hasDiff = diff && (Object.keys(diff.changed || {}).length > 0 || Object.keys(diff.added || {}).length > 0 || Object.keys(diff.removed || {}).length > 0);

          return (
            <div
              key={alert.id}
              className="rounded-lg p-3 flex flex-col gap-2"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div
                    className="w-8 h-8 rounded-md flex items-center justify-center shrink-0"
                    style={{
                      background: 'color-mix(in srgb, var(--color-accent) 12%, transparent)',
                    }}
                  >
                    <Shield size={16} style={{ color: 'var(--color-accent)' }} />
                  </div>
                  <div className="flex flex-col min-w-0">
                    <span className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                      {alert.target}
                    </span>
                    <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                      <span>{alert.type}</span>
                      <span>·</span>
                      <span>{new Date(alert.timestamp).toLocaleString()}</span>
                    </div>
                  </div>
                </div>

                {hasDiff && (
                  <button
                    onClick={() => toggleExpand(alert.id)}
                    className="p-1.5 rounded-md transition-colors cursor-pointer"
                    style={{ color: 'var(--color-text-tertiary)' }}
                    title={isExpanded ? 'Collapse' : 'Expand'}
                  >
                    {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                )}
              </div>

              {isExpanded && hasDiff && (
                <div className="flex flex-col gap-3 mt-1 pl-11">
                  {formatDiff(diff)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
