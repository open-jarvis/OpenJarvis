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
import { Zap, Activity, Thermometer, Hash } from 'lucide-react';
import { fetchEnergy, fetchTelemetry } from '../../lib/api';

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
    <div
      className="rounded-lg p-4"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon size={14} style={{ color: 'var(--color-accent)' }} />
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
      </div>
      <div className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
        {value}
        {unit && (
          <span className="text-xs font-normal ml-1" style={{ color: 'var(--color-text-tertiary)' }}>
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

export function EnergyDashboard() {
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
      <div
        className="rounded-xl p-6"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <h3 className="text-sm font-medium mb-4 flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
          <Zap size={16} style={{ color: 'var(--color-accent)' }} />
          Energy Monitoring
        </h3>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          {error || 'Waiting for energy data from the server...'}
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl p-6"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-medium mb-4 flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
        <Zap size={16} style={{ color: 'var(--color-accent)' }} />
        Energy Monitoring
      </h3>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
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
          value={String(telemetry?.total_requests ?? 0)}
        />
      </div>

      {/* Thermal indicator */}
      <div className="flex items-center gap-2 mb-4 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        <span className="w-2 h-2 rounded-full" style={{ background: thermalStatus.color }} />
        Thermal: {thermalStatus.label}
        <span className="ml-auto">{telemetry?.total_tokens ?? 0} tokens processed</span>
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
