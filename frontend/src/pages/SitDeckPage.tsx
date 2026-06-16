import { useEffect, useState, useCallback } from 'react';
import { Map, Database, Layers, Boxes, FileText, Users, RefreshCw, AlertCircle } from 'lucide-react';
import { fetchSitDeckHealth, fetchSitDeckEndpoint } from '../lib/api';

const ENDPOINTS = [
  { key: 'widgets', label: 'Widgets', icon: Boxes, color: 'var(--color-accent-purple)' },
  { key: 'data_sources', label: 'Data Sources', icon: Database, color: 'var(--color-accent)' },
  { key: 'map_capabilities', label: 'Map Layers', icon: Layers, color: 'var(--color-success)' },
  { key: 'map_types', label: 'Map Types', icon: Map, color: 'var(--color-warning)' },
  { key: 'plans', label: 'Plans', icon: FileText, color: 'var(--color-accent-amber)' },
  { key: 'customer_count', label: 'Customers', icon: Users, color: 'var(--color-accent-purple)' },
  { key: 'content', label: 'Content', icon: FileText, color: 'var(--color-text-secondary)' },
];

interface EndpointHealth {
  status: string;
  status_code?: number;
  size?: number;
  error?: string;
}

interface HealthData {
  status: string;
  sitdeck?: {
    status: string;
    total_up: number;
    total_endpoints: number;
    sources: Record<string, EndpointHealth>;
  };
}

interface EndpointResult {
  status: string;
  result?: {
    endpoint: string;
    status_code: number;
    data?: unknown;
  };
}

const formatNumber = (n: number | undefined | null): string | null => {
  if (n === undefined || n === null || Number.isNaN(n)) return null;
  return new Intl.NumberFormat('en-US').format(n);
};

export function SitDeckPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [results, setResults] = useState<Record<string, EndpointResult>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const healthRes = (await fetchSitDeckHealth()) as HealthData;
      setHealth(healthRes);

      const next: Record<string, EndpointResult> = {};
      await Promise.all(
        ENDPOINTS.map(async ({ key }) => {
          try {
            next[key] = (await fetchSitDeckEndpoint(key)) as EndpointResult;
          } catch (e) {
            next[key] = { status: 'error', result: { endpoint: key, status_code: 0, data: String(e) } };
          }
        }),
      );
      setResults(next);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const sitdeck = health?.sitdeck;
  const totalUp = sitdeck?.total_up ?? 0;
  const totalEndpoints = sitdeck?.total_endpoints ?? 0;

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-6xl mx-auto">
        <header className="glass p-4 mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
              <Map size={18} style={{ color: 'var(--color-accent-purple)' }} />
              SitDeck Command Center
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Live read-only view of SitDeck public APIs — widgets, data sources, maps, plans and content.
            </p>
          </div>
          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium cursor-pointer transition-colors"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </header>

        {error && (
          <div
            role="alert"
            className="glass p-3 mb-4 flex items-center gap-2 text-xs"
            style={{ color: 'var(--color-error)', borderColor: 'var(--color-error)' }}
          >
            <AlertCircle size={14} aria-hidden="true" />
            {error}
          </div>
        )}

        {sitdeck && (
          <div className="glass p-3 mb-6 flex flex-wrap gap-3">
            <StatusBadge
              label="Endpoints"
              value={`${totalUp}/${totalEndpoints} up`}
              color={totalUp === totalEndpoints ? 'var(--color-success)' : 'var(--color-warning)'}
            />
            <StatusBadge
              label="Overall"
              value={sitdeck.status}
              color={sitdeck.status === 'up' ? 'var(--color-success)' : 'var(--color-error)'}
            />
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <EndpointCard
            endpoint={ENDPOINTS[0]}
            result={results.widgets}
            health={sitdeck?.sources?.widgets}
            render={(data) => (
              <>
                <Metric label="Total Widgets" value={formatNumber(data.totalWidgets)} />
                <Metric label="Map Overlays" value={formatNumber(data.totalMapOverlays)} />
                <Metric label="Categories" value={formatNumber(data.widgetCategories?.length)} />
              </>
            )}
          />
          <EndpointCard
            endpoint={ENDPOINTS[1]}
            result={results.data_sources}
            health={sitdeck?.sources?.data_sources}
            render={(data) => (
              <>
                <Metric label="Total Sources" value={formatNumber(data.totalDataSources)} />
                <Metric label="Online" value={formatNumber(data.summary?.online)} color="var(--color-success)" />
                <Metric label="Errored" value={formatNumber(data.summary?.errored)} color="var(--color-error)" />
                <Metric label="On Demand" value={formatNumber(data.summary?.onDemand)} />
              </>
            )}
          />
          <EndpointCard
            endpoint={ENDPOINTS[2]}
            result={results.map_capabilities}
            health={sitdeck?.sources?.map_capabilities}
            render={(data) => (
              <>
                <Metric label="Total Layers" value={formatNumber(data.summary?.totalLayers)} />
                <Metric label="Map Types" value={formatNumber(data.summary?.totalMapTypes)} />
                <Metric label="Layer Groups" value={formatNumber(data.summary?.layerGroups)} />
                <Metric label="Globe 3D" value={formatNumber(data.summary?.globe3D)} />
              </>
            )}
          />
          <EndpointCard
            endpoint={ENDPOINTS[3]}
            result={results.map_types}
            health={sitdeck?.sources?.map_types}
            render={(data) => (
              <>
                <Metric label="Total Map Types" value={formatNumber(data.totalMapTypes)} />
                <Metric label="Vector Maps" value={formatNumber(data.summary?.vectorMaps)} />
                <Metric label="Projections" value={formatNumber(data.summary?.nonMercatorProjections)} />
                <Metric label="Globe 3D" value={formatNumber(data.summary?.globe3D)} />
              </>
            )}
          />
          <EndpointCard
            endpoint={ENDPOINTS[4]}
            result={results.plans}
            health={sitdeck?.sources?.plans}
            render={(data) => (
              <>
                <Metric label="Total Plans" value={formatNumber(data.totalPlans)} />
                {data.plans?.slice(0, 3).map((plan: { id: string; name: string }) => (
                  <div key={plan.id} className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    • {plan.name}
                  </div>
                ))}
              </>
            )}
          />
          <EndpointCard
            endpoint={ENDPOINTS[5]}
            result={results.customer_count}
            health={sitdeck?.sources?.customer_count}
            render={(data) => <Metric label="Registered Customers" value={formatNumber(data.count)} />}
          />
        </div>

        <EndpointCard
          endpoint={ENDPOINTS[6]}
          result={results.content}
          health={sitdeck?.sources?.content}
          fullWidth
          render={(data) => (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
              {(Array.isArray(data) ? data : []).slice(0, 12).map((item: { id: number; section: string; key: string; content: string }) => (
                <div
                  key={item.id}
                  className="p-2 rounded text-xs"
                  style={{ background: 'var(--color-bg-secondary)' }}
                >
                  <span style={{ color: 'var(--color-text-tertiary)' }}>{item.section}</span>
                  <div style={{ color: 'var(--color-text)' }}>{item.content}</div>
                </div>
              ))}
            </div>
          )}
        />
      </div>
    </div>
  );
}

function StatusBadge({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-full"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border-subtle)' }}
    >
      <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-secondary)' }}>{label}</span>
      <span className="text-[11px] font-semibold" style={{ color }}>{value}</span>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value?: number | string | null; color?: string }) {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div className="flex items-center justify-between text-xs py-1" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <span style={{ color: 'var(--color-text-secondary)' }}>{label}</span>
      <span className="font-semibold" style={{ color: color || 'var(--color-text)' }}>{value}</span>
    </div>
  );
}

function EndpointCard({
  endpoint,
  result,
  health,
  render,
  fullWidth = false,
}: {
  endpoint: (typeof ENDPOINTS)[number];
  result?: EndpointResult;
  health?: EndpointHealth;
  render: (data: any) => React.ReactNode;
  fullWidth?: boolean;
}) {
  const Icon = endpoint.icon;
  const statusColor =
    health?.status === 'up'
      ? 'var(--color-success)'
      : health?.status === 'degraded'
        ? 'var(--color-warning)'
        : 'var(--color-error)';

  const data = result?.result?.data;
  const failed = !result || result.status !== 'ok';

  return (
    <div
      className={`hud-panel p-4 ${fullWidth ? 'md:col-span-2' : ''}`}
      style={{ border: `1px solid ${failed ? 'var(--color-error)' : 'var(--color-border)'}` }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="hud-label flex items-center gap-2">
          <Icon size={12} style={{ color: endpoint.color }} />
          {endpoint.label}
        </h3>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded font-medium"
          style={{ background: statusColor + '20', color: statusColor }}
        >
          {health?.status || 'unknown'}
        </span>
      </div>

      {failed ? (
        <div className="text-xs" style={{ color: 'var(--color-error)' }}>
          {result?.result?.data ? String(result.result.data) : 'Loading…'}
        </div>
      ) : (
        <div className="flex flex-col">{render(data)}</div>
      )}
    </div>
  );
}
