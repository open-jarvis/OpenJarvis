import { useEffect, useState, useCallback } from 'react';
import { Bot, Shield, Hotel, Zap } from 'lucide-react';
import { fetchManagedAgents, fetchOsintStats, fetchLandhausHealth, fetchTelemetry } from '../../lib/api';

interface StatusBadge {
  icon: typeof Bot;
  label: string;
  value: string;
  color: string;
}

export function GlobalStatusStrip() {
  const [badges, setBadges] = useState<StatusBadge[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [agents, osint, landhaus, telemetry] = await Promise.allSettled([
        fetchManagedAgents().catch(() => []),
        fetchOsintStats().catch(() => ({} as { total_alerts_today?: number })),
        fetchLandhausHealth().catch(() => ({} as { sources?: Record<string, { status: string }> })),
        fetchTelemetry().catch(() => ({} as { total_tokens?: number; power_w?: number })),
      ]);

      const next: StatusBadge[] = [];

      if (agents.status === 'fulfilled') {
        const running = agents.value.filter((a) => a.status === 'running').length;
        const errors = agents.value.filter((a) => a.status === 'error' || a.status === 'needs_attention').length;
        next.push({
          icon: Bot,
          label: 'Agents',
          value: errors > 0 ? `${running} running · ${errors} error` : `${running} running`,
          color: errors > 0 ? 'var(--color-error)' : 'var(--color-accent)',
        });
      }

      if (osint.status === 'fulfilled') {
        const alerts = osint.value.total_alerts_today ?? 0;
        next.push({
          icon: Shield,
          label: 'OSINT',
          value: `${alerts} alert${alerts !== 1 ? 's' : ''} today`,
          color: alerts > 0 ? 'var(--color-warning)' : 'var(--color-success)',
        });
      }

      if (landhaus.status === 'fulfilled') {
        const data = landhaus.value as { sources?: Record<string, { status: string }> };
        if (data.sources) {
          const down = Object.values(data.sources).filter((s) => s.status === 'down' || s.status === 'error').length;
          next.push({
            icon: Hotel,
            label: 'Landhaus',
            value: down > 0 ? `${down} service${down > 1 ? 's' : ''} down` : 'All services ok',
            color: down > 0 ? 'var(--color-error)' : 'var(--color-success)',
          });
        }
      }

      if (telemetry.status === 'fulfilled') {
        const data = telemetry.value as { total_tokens?: number; power_w?: number };
        const tokens = data.total_tokens ?? 0;
        const powerW = data.power_w ?? 0;
        next.push({
          icon: Zap,
          label: 'Inference',
          value: powerW > 0
            ? `${formatWatts(powerW)} · ${formatTokens(tokens)} tokens`
            : `${formatTokens(tokens)} tokens`,
          color: 'var(--color-accent)',
        });
      }

      setBadges(next);
      setError(null);
    } catch {
      setError('Status fetch failed');
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, [refresh]);

  if (error) {
    return (
      <div role="alert" className="glass p-3 mb-4 text-xs" style={{ color: 'var(--color-error)' }}>
        {error}
      </div>
    );
  }

  return (
    <div className="glass p-3 mb-4 flex flex-wrap gap-3">
      {badges.map((badge) => (
        <div
          key={badge.label}
          className="flex items-center gap-2 px-3 py-1.5 rounded-full"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border-subtle)',
          }}
        >
          <badge.icon size={12} style={{ color: badge.color }} />
          <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            {badge.label}
          </span>
          <span className="text-[11px] font-semibold" style={{ color: badge.color }}>
            {badge.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatWatts(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}kW`;
  return `${Math.round(n)}W`;
}
