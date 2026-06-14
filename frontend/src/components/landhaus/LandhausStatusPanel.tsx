import { useEffect, useState, useCallback } from 'react';
import { Activity, Globe, Calendar, Server, CheckCircle, AlertTriangle, XCircle, Loader2, RefreshCw } from 'lucide-react';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

interface SourceHealth {
  status: string;
  status_code?: number;
  error?: string;
  content_length?: number;
  latest_state?: string;
  latest_url?: string;
  rooms_total?: number;
  rooms_occupied?: number;
  rooms_available?: number;
  next_checkin?: string;
  bookings_count?: number;
  last_sync?: string;
  channels?: string[];
  deployment_state?: string;
  production_url?: string;
  last_deploy?: string;
}

interface HealthResponse {
  status: string;
  sources: Record<string, SourceHealth>;
}

function useLandhausHealth() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch(`${API_URL}/v1/landhaus/health`);
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const json = (await resp.json()) as HealthResponse;
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { data, loading, error, reload: load };
}

export function LandhausStatusPanel() {
  const { data, loading, error, reload } = useLandhausHealth();

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-20 gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        <Loader2 size={14} className="animate-spin" />
        Loading Landhaus Bavaria status...
      </div>
    );
  }

  if (error) {
    return (
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
        <button
          onClick={reload}
          className="ml-auto text-xs underline cursor-pointer"
          style={{ color: 'var(--color-accent)' }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const sources = data.sources || {};

  return (
    <div className="flex flex-col gap-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={16} style={{ color: 'var(--color-accent)' }} />
          <h2 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            Landhaus Bavaria — System Health
          </h2>
        </div>
        <button
          onClick={reload}
          className="flex items-center gap-1.5 text-[10px] px-2 py-1.5 rounded-md cursor-pointer"
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatusCard
          icon={Globe}
          label="Website"
          source={sources.website}
          accent="#38bdf8"
        />
        <StatusCard
          icon={Server}
          label="Deskline"
          source={sources.deskline}
          accent="#a78bfa"
        />
        <StatusCard
          icon={Calendar}
          label="iCal Sync"
          source={sources.ical}
          accent="#f472b6"
        />
        <StatusCard
          icon={Activity}
          label="Vercel"
          source={sources.vercel}
          accent="#fb923c"
        />
      </div>

      {/* Raw JSON */}
      <div
        className="rounded-lg p-4"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      >
        <h3 className="text-xs font-medium mb-2" style={{ color: 'var(--color-text)' }}>
          Raw Response
        </h3>
        <pre
          className="text-[10px] overflow-auto rounded p-2"
          style={{
            background: 'var(--color-bg-primary)',
            color: 'var(--color-text-secondary)',
            maxHeight: '200px',
          }}
        >
          {JSON.stringify(data, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function StatusCard({
  icon: Icon,
  label,
  source,
  accent,
}: {
  icon: React.ElementType;
  label: string;
  source?: SourceHealth;
  accent: string;
}) {
  const status = source?.status || 'unknown';
  const isUp = status === 'up';
  const isDown = status === 'down';
  const isDemo = status === 'demo';

  const StatusIcon = isUp ? CheckCircle : isDown ? XCircle : AlertTriangle;
  const statusColor = isUp ? '#4ade80' : isDown ? 'var(--color-error)' : isDemo ? '#38bdf8' : '#facc15';

  return (
    <div
      className="rounded-lg p-3 flex flex-col gap-2"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-2">
        <div
          className="w-8 h-8 rounded-md flex items-center justify-center shrink-0"
          style={{ background: `color-mix(in srgb, ${accent} 12%, transparent)` }}
        >
          <Icon size={16} style={{ color: accent }} />
        </div>
        <div className="flex flex-col">
          <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
            {label}
          </span>
          <span className="text-[10px] flex items-center gap-1" style={{ color: statusColor }}>
            <StatusIcon size={10} />
            {status}
          </span>
        </div>
      </div>

      {source?.status_code && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Status code: {source.status_code}
        </div>
      )}

      {source?.latest_state && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          State: {source.latest_state}
        </div>
      )}

      {source?.content_length && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Content: {source.content_length} bytes
        </div>
      )}

      {source?.error && (
        <div
          className="text-[10px] px-2 py-1 rounded"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            color: 'var(--color-error)',
          }}
        >
          {source.error}
        </div>
      )}

      {/* Demo / extra fields */}
      {(source?.rooms_available != null || source?.rooms_total != null) && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Rooms: {source.rooms_occupied ?? '-'}/{source.rooms_total ?? '-'} occupied, {source.rooms_available ?? '-'} free
        </div>
      )}
      {source?.next_checkin && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Next check-in: {source.next_checkin}
        </div>
      )}
      {source?.bookings_count != null && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Bookings: {source.bookings_count}
        </div>
      )}
      {source?.last_sync && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Last sync: {new Date(source.last_sync).toLocaleDateString()}
        </div>
      )}
      {source?.deployment_state && (
        <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Deploy: {source.deployment_state}
        </div>
      )}
      {source?.production_url && (
        <div className="text-[10px] truncate" style={{ color: 'var(--color-text-tertiary)' }}>
          URL: {source.production_url}
        </div>
      )}
    </div>
  );
}
