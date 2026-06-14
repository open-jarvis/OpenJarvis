import { useEffect, useState, useCallback } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
} from 'recharts';
import {
  Activity,
  ScanLine,
  Terminal,
  Target,
  TrendingUp,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import { fetchDashboardStats, fetchAlerts, type DashboardStats, type AlertsResponse } from '../Desktop/lib/api';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

const ACCENTS = [
  'var(--color-accent)',
  '#38bdf8',
  '#a78bfa',
  '#f472b6',
  '#fb923c',
];

function useDashboardStats() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [data, alertData] = await Promise.all([
        fetchDashboardStats(API_URL),
        fetchAlerts(API_URL, 10),
      ]);
      setStats(data);
      setAlerts(alertData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load stats');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { stats, alerts, loading, error, reload: load };
}

export function DashboardPanel() {
  const { stats, alerts, loading, error, reload } = useDashboardStats();

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center py-20 gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        <Loader2 size={14} className="animate-spin" />
        Loading dashboard...
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

  if (!stats) return null;

  const isEmpty = stats.total_actions === 0;

  return (
    <div className="flex flex-col gap-6 max-w-5xl mx-auto">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SummaryCard
          icon={ScanLine}
          label="Total Scans"
          value={stats.total_scans}
          accent="var(--color-accent)"
        />
        <SummaryCard
          icon={Terminal}
          label="Total Executions"
          value={stats.total_execs}
          accent="#38bdf8"
        />
        <SummaryCard
          icon={TrendingUp}
          label="Success Rate"
          value={`${stats.success_rate}%`}
          accent="#a78bfa"
        />
        <SummaryCard
          icon={Target}
          label="Unique Targets"
          value={stats.unique_targets}
          accent="#f472b6"
        />
      </div>

      {isEmpty ? (
        <div
          className="rounded-lg p-8 text-center text-sm"
          style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}
        >
          <Activity size={24} className="mx-auto mb-2 opacity-50" />
          No activity yet. Run a Watchdog scan or execute a tool to see stats.
        </div>
      ) : (
        <>
          {/* Alerts */}
          {alerts && alerts.count > 0 && (
            <div
              className="rounded-lg p-4"
              style={{ background: 'color-mix(in srgb, var(--color-accent) 4%, var(--color-bg-secondary))', border: '1px solid var(--color-accent-muted)' }}
            >
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle size={14} style={{ color: 'var(--color-accent)' }} />
                <h3 className="text-xs font-medium" style={{ color: 'var(--color-accent)' }}>
                  Recent Alerts ({alerts.count})
                </h3>
              </div>
              <div className="flex flex-col gap-2 max-h-40 overflow-auto">
                {alerts.alerts.map((alert) => {
                  const diff = alert.metadata?.diff;
                  const changedKeys = diff ? Object.keys({ ...diff.changed, ...diff.added, ...diff.removed }) : [];
                  return (
                    <div
                      key={alert.id}
                      className="rounded-md p-2 flex items-center justify-between gap-2"
                      style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
                    >
                      <div className="flex flex-col min-w-0">
                        <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
                          {alert.target}
                        </span>
                        <span className="text-[10px] truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                          {changedKeys.slice(0, 3).join(', ')}
                          {changedKeys.length > 3 && ` +${changedKeys.length - 3} more`}
                        </span>
                      </div>
                      <span className="text-[10px] shrink-0" style={{ color: 'var(--color-text-tertiary)' }}>
                        {new Date(alert.timestamp).toLocaleDateString()}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Activity Timeline */}
          <div
            className="rounded-lg p-4"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <h3 className="text-xs font-medium mb-3 flex items-center gap-1.5" style={{ color: 'var(--color-text)' }}>
              <Activity size={14} style={{ color: 'var(--color-accent)' }} />
              Activity Timeline (30 days)
            </h3>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={stats.activity_timeline}>
                  <defs>
                    <linearGradient id="scansGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="var(--color-accent)" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="execsGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.5} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(v) => v.slice(5)}
                    stroke="var(--color-text-tertiary)"
                    tick={{ fontSize: 10 }}
                    interval={4}
                  />
                  <YAxis stroke="var(--color-text-tertiary)" tick={{ fontSize: 10 }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      background: 'var(--color-bg-primary)',
                      border: '1px solid var(--color-border)',
                      fontSize: 12,
                    }}
                    labelStyle={{ color: 'var(--color-text)' }}
                  />
                  <Area
                    type="monotone"
                    dataKey="scans"
                    stroke="var(--color-accent)"
                    fillOpacity={1}
                    fill="url(#scansGrad)"
                    name="Scans"
                  />
                  <Area
                    type="monotone"
                    dataKey="execs"
                    stroke="#38bdf8"
                    fillOpacity={1}
                    fill="url(#execsGrad)"
                    name="Execs"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Bottom grid: Top Targets + Tool Usage + Module Usage */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {/* Top Targets */}
            <div
              className="rounded-lg p-4"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-xs font-medium mb-3" style={{ color: 'var(--color-text)' }}>
                Top Targets
              </h3>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={stats.top_targets} layout="vertical" margin={{ left: 10, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.3} />
                    <XAxis type="number" stroke="var(--color-text-tertiary)" tick={{ fontSize: 10 }} allowDecimals={false} />
                    <YAxis dataKey="target" type="category" stroke="var(--color-text-tertiary)" tick={{ fontSize: 10 }} width={80} />
                    <Tooltip
                      contentStyle={{
                        background: 'var(--color-bg-primary)',
                        border: '1px solid var(--color-border)',
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="count" fill="var(--color-accent)" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Tool Usage */}
            <div
              className="rounded-lg p-4"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-xs font-medium mb-3" style={{ color: 'var(--color-text)' }}>
                Tool Usage
              </h3>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip
                      contentStyle={{
                        background: 'var(--color-bg-primary)',
                        border: '1px solid var(--color-border)',
                        fontSize: 12,
                      }}
                    />
                    <Pie
                      data={stats.tool_usage}
                      dataKey="count"
                      nameKey="tool_name"
                      cx="50%"
                      cy="50%"
                      innerRadius={30}
                      outerRadius={55}
                      paddingAngle={3}
                    >
                      {stats.tool_usage.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={ACCENTS[index % ACCENTS.length]} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1">
                {stats.tool_usage.map((t, i) => (
                  <div key={t.tool_name} className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-full" style={{ background: ACCENTS[i % ACCENTS.length] }} />
                    <span className="text-[10px]" style={{ color: 'var(--color-text-secondary)' }}>
                      {t.tool_name}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Module Usage */}
            <div
              className="rounded-lg p-4"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-xs font-medium mb-3" style={{ color: 'var(--color-text)' }}>
                Module Usage
              </h3>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={stats.module_usage} layout="vertical" margin={{ left: 10, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.3} />
                    <XAxis type="number" stroke="var(--color-text-tertiary)" tick={{ fontSize: 10 }} allowDecimals={false} />
                    <YAxis dataKey="module" type="category" stroke="var(--color-text-tertiary)" tick={{ fontSize: 10 }} width={60} />
                    <Tooltip
                      contentStyle={{
                        background: 'var(--color-bg-primary)',
                        border: '1px solid var(--color-border)',
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="count" fill="#a78bfa" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  accent: string;
}) {
  return (
    <div
      className="rounded-lg p-3 flex items-center gap-3"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div
        className="w-8 h-8 rounded-md flex items-center justify-center shrink-0"
        style={{ background: `color-mix(in srgb, ${accent} 12%, transparent)` }}
      >
        <Icon size={16} style={{ color: accent }} />
      </div>
      <div className="flex flex-col">
        <span className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
          {value}
        </span>
        <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
      </div>
    </div>
  );
}
