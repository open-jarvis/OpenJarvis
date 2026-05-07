import { useState, useEffect, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Zap, Activity, Thermometer, Hash, Gauge } from 'lucide-react';
import { fetchEnergy, fetchTelemetry } from '../../lib/api';
import { useAppStore } from '../../lib/store';

interface EnergySample {
  timestamp: string;
  power_w: number;
  energy_j: number;
}

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  samples?: EnergySample[];
}

interface TelemetryStats {
  total_requests?: number;
  total_tokens?: number;
}

interface ChartPoint {
  time: string;
  power: number;
}

function StatCard({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="hud-panel p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={12} style={{ color: 'var(--color-accent)' }} />
        <span className="hud-label">{label}</span>
      </div>
      <div className="hud-mono text-2xl font-semibold truncate" style={{ color: 'var(--color-text)' }}>
        {value}
        {unit && (
          <span className="hud-label ml-1" style={{ fontSize: '0.625rem', letterSpacing: '0.18em' }}>
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

export function EnergyDashboard() {
  const savings = useAppStore((s) => s.savings);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [energyRes, telRes] = await Promise.allSettled([
        fetchEnergy().catch(() => null),
        fetchTelemetry().catch(() => null),
      ]);

      if (energyRes.status === 'fulfilled' && energyRes.value) {
        const data = energyRes.value as EnergyData;
        setEnergy(data);
        if (data.samples) {
          setChartData(
            data.samples.map((s) => ({
              time: new Date(s.timestamp).toLocaleTimeString(),
              power: Math.round(s.power_w * 10) / 10,
            })),
          );
        }
        setError(null);
      }
      if (telRes.status === 'fulfilled' && telRes.value) {
        setTelemetry(telRes.value as TelemetryStats);
      }
    } catch {
      setError('Cannot connect to server');
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const thermalStatus = (energy?.avg_power_w ?? 0) < 50
    ? { label: 'Cool', color: 'var(--color-success)' }
    : (energy?.avg_power_w ?? 0) < 150
    ? { label: 'Warm', color: 'var(--color-warning)' }
    : { label: 'Hot', color: 'var(--color-error)' };

  if (error || !energy) {
    return (
      <div className="hud-panel p-6">
        <h3 className="hud-label flex items-center gap-2 mb-4">
          <Zap size={12} style={{ color: 'var(--color-accent)' }} />
          Energy Monitoring
        </h3>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span className="hud-mono">{error || 'awaiting telemetry stream…'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="hud-panel p-6">
      <h3 className="hud-label flex items-center gap-2 mb-4">
        <Zap size={12} style={{ color: 'var(--color-accent)' }} />
        Energy Monitoring
      </h3>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatCard
          icon={Zap}
          label="Total Energy"
          value={((energy.total_energy_j ?? 0) / 1000).toFixed(1)}
          unit="kJ"
        />
        <StatCard
          icon={Activity}
          label="Energy / Token"
          value={(energy.energy_per_token_j ?? 0).toFixed(3)}
          unit="J"
        />
        <StatCard
          icon={Thermometer}
          label="Avg Power"
          value={(energy.avg_power_w ?? 0).toFixed(1)}
          unit="W"
        />
        <StatCard
          icon={Hash}
          label="Total Requests"
          value={String(savings?.total_calls ?? telemetry?.total_requests ?? 0)}
        />
        <StatCard
          icon={Gauge}
          label="Thermal"
          value={thermalStatus.label}
        />
        <StatCard
          icon={Hash}
          label="Tokens Processed"
          value={formatNumber(savings?.total_tokens ?? telemetry?.total_tokens ?? 0)}
        />
      </div>

      {/* Chart */}
      {chartData.length > 1 && (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} unit="W" />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: 12,
                  color: 'var(--color-text)',
                }}
              />
              <Line type="monotone" dataKey="power" stroke="var(--color-accent)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
