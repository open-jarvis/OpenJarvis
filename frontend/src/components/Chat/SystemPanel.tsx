import { useState, useEffect, useCallback } from 'react';
import {
  Zap,
  Activity,
  Thermometer,
  DollarSign,
  TrendingDown,
  Cloud,
  HardDrive,
  Hash,
  X,
  Trophy,
  ExternalLink,
  Shield,
  Eye,
} from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { getBase, fetchAuditLog, fetchHooks, type AuditEntry, type HookInfo } from '../../lib/api';

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  cpu_temp_c?: number | null;
  gpu_temp_c?: number | null;
}

interface TelemetryStats {
  total_requests?: number;
  total_tokens?: number;
}

const CLOUD_PRICING = [
  { name: 'GPT-5.3', input: 2.00, output: 10.00, primary: true },
  { name: 'Claude Opus 4.6', input: 5.00, output: 25.00, primary: false },
  { name: 'Gemini 3.1 Pro', input: 2.00, output: 12.00, primary: false },
];

export function SystemPanel() {
  const savings = useAppStore((s) => s.savings);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const setOptInModalOpen = useAppStore((s) => s.setOptInModalOpen);
  const liveEnergy = useAppStore((s) => s.liveEnergy);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const [hooks, setHooks] = useState<HookInfo[]>([]);
  const [securityExpanded, setSecurityExpanded] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const base = getBase();
      const [energyRes, telRes] = await Promise.allSettled([
        fetch(`${base}/v1/telemetry/energy`).then((r) => (r.ok ? r.json() : null)),
        fetch(`${base}/v1/telemetry/stats`).then((r) => (r.ok ? r.json() : null)),
      ]);
      if (energyRes.status === 'fulfilled' && energyRes.value) {
        setEnergy(energyRes.value as EnergyData);
      }
      if (telRes.status === 'fulfilled' && telRes.value) {
        setTelemetry(telRes.value as TelemetryStats);
      }
      // Security / audit best-effort
      try {
        const audit = await fetchAuditLog(10);
        setAuditLog(audit.entries);
      } catch {
        setAuditLog([]);
      }
      try {
        const hookList = await fetchHooks();
        setHooks(hookList);
      } catch {
        setHooks([]);
      }
    } catch {
      // best-effort
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Re-fetch energy/telemetry when savings updates (after a chat message)
  useEffect(() => {
    if (savings) fetchData();
  }, [savings, fetchData]);

  const promptK = (savings?.total_prompt_tokens ?? 0) / 1000;
  const completionK = (savings?.total_completion_tokens ?? 0) / 1000;

  return (
    <div
      className="flex flex-col h-full overflow-y-auto"
      style={{
        width: 280,
        minWidth: 280,
        background: 'var(--color-bg)',
        borderLeft: '1px solid var(--color-border)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <span className="text-xs font-semibold tracking-wide uppercase" style={{ color: 'var(--color-text-secondary)' }}>
          System
        </span>
        <button
          onClick={toggleSystemPanel}
          className="p-1 rounded-md transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title="Close panel"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex flex-col gap-4 p-4">
        {/* Session Stats */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Session
          </h4>
          <div className="grid grid-cols-2 gap-2">
            <MiniStat icon={Hash} label="Requests" value={String(savings?.total_calls ?? telemetry?.total_requests ?? 0)} />
            <MiniStat icon={Hash} label="Output Tokens" value={formatNumber(savings?.total_completion_tokens ?? telemetry?.total_tokens ?? 0)} />
          </div>
        </section>

        {/* Device */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Device
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {energy?.cpu_temp_c != null && (
              <MiniStat icon={Thermometer} label="CPU Temp" value={String(Math.round(energy.cpu_temp_c))} unit="°C" />
            )}
            {energy?.gpu_temp_c != null && (
              <MiniStat icon={Thermometer} label="GPU Temp" value={String(Math.round(energy.gpu_temp_c))} unit="°C" />
            )}
            <MiniStat
              icon={Zap}
              label="Power"
              value={(liveEnergy?.power_w ?? energy?.avg_power_w ?? 0).toFixed(1)}
              unit="W"
            />
            <MiniStat
              icon={Activity}
              label="Energy"
              value={(
                ((liveEnergy?.energy_j ?? energy?.total_energy_j ?? 0) / 1000)
              ).toFixed(1)}
              unit="kJ"
            />
          </div>
        </section>


        {/* Cost Comparison */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Cost Comparison
          </h4>

          {/* Local */}
          <div
            className="flex items-center gap-2 rounded-lg px-3 py-2 mb-2"
            style={{ background: 'var(--color-accent-subtle)', border: '1px solid var(--color-accent)' }}
          >
            <HardDrive size={14} style={{ color: 'var(--color-accent)' }} />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate" style={{ color: 'var(--color-text)' }}>Local</div>
            </div>
            <div className="text-sm font-semibold" style={{ color: 'var(--color-success)' }}>
              ${(savings?.local_cost ?? 0).toFixed(4)}
            </div>
          </div>

          {/* Cloud providers */}
          <div className="flex flex-col gap-1.5">
            {CLOUD_PRICING.map((provider) => {
              const cost = (promptK * provider.input) / 1000 + (completionK * provider.output) / 1000;
              const saved = cost - (savings?.local_cost ?? 0);
              return (
                <div
                  key={provider.name}
                  className="flex items-center gap-2 rounded-lg px-3 py-2"
                  style={{
                    background: provider.primary ? 'var(--color-bg-secondary)' : 'var(--color-bg-secondary)',
                    border: provider.primary ? '1px solid var(--color-border-accent, var(--color-accent))' : '1px solid transparent',
                  }}
                >
                  <Cloud size={14} style={{ color: 'var(--color-text-tertiary)' }} />
                  <div className="flex-1 min-w-0">
                    <div
                      className="text-xs truncate"
                      style={{
                        color: provider.primary ? 'var(--color-text)' : 'var(--color-text-secondary)',
                        fontWeight: provider.primary ? 500 : 400,
                      }}
                    >
                      {provider.name}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-xs font-mono" style={{ color: 'var(--color-text)' }}>
                      ${cost.toFixed(4)}
                    </div>
                    {saved > 0.0001 && (
                      <div className="text-[9px] flex items-center gap-0.5 justify-end" style={{ color: 'var(--color-success)' }}>
                        <TrendingDown size={8} />
                        ${saved.toFixed(4)}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>


        </section>

        {/* Security & Audit */}
        <section>
          <button
            onClick={() => setSecurityExpanded(!securityExpanded)}
            className="w-full flex items-center gap-2 mb-2 cursor-pointer"
          >
            <Shield size={14} style={{ color: 'var(--color-accent)' }} />
            <h4
              className="text-[11px] font-medium uppercase tracking-wide"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              Security & Audit
            </h4>
            <span className="ml-auto text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
              {securityExpanded ? '▼' : '▶'}
            </span>
          </button>

          {securityExpanded && (
            <div className="flex flex-col gap-3">
              {/* Hooks */}
              <div className="flex flex-wrap gap-1">
                {hooks.map((h) => (
                  <span
                    key={h.name}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]"
                    style={{
                      background: h.active
                        ? 'var(--color-accent-subtle)'
                        : 'var(--color-bg-secondary)',
                      color: h.active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                      border: `1px solid ${h.active ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    }}
                    title={`Stage: ${h.stage} | Priority: ${h.priority}`}
                  >
                    {h.active ? '●' : '○'} {h.name}
                  </span>
                ))}
                {hooks.length === 0 && (
                  <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                    No hooks registered
                  </span>
                )}
              </div>

              {/* Audit Trail */}
              <div className="flex flex-col gap-1 max-h-40 overflow-y-auto">
                {auditLog.slice(0, 10).map((entry, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-2 text-[10px] px-2 py-1 rounded"
                    style={{
                      background: entry.allowed
                        ? 'rgba(34,197,94,0.08)'
                        : 'rgba(239,68,68,0.08)',
                    }}
                  >
                    <Eye size={10} style={{ color: entry.allowed ? 'var(--color-success)' : 'var(--color-error)', opacity: 0.7 }} />
                    <span className="font-mono opacity-60">
                      {new Date(entry.timestamp).toLocaleTimeString()}
                    </span>
                    <span className="truncate flex-1">{entry.agent_id} › {entry.stage}</span>
                    {entry.error && (
                      <span className="text-[9px] shrink-0" style={{ color: 'var(--color-error)' }}>
                        {entry.error}
                      </span>
                    )}
                  </div>
                ))}
                {auditLog.length === 0 && (
                  <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                    No audit entries
                  </span>
                )}
              </div>
            </div>
          )}
        </section>

        {/* Leaderboard / Share */}
        <section>
          <h4
            className="text-[11px] font-medium uppercase tracking-wide mb-2"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Leaderboard
          </h4>

          <button
            onClick={() => setOptInModalOpen(true)}
            className="w-full flex items-center gap-2 rounded-lg px-3 py-2.5 transition-colors cursor-pointer"
            style={{
              background: optInEnabled
                ? 'var(--color-accent-subtle)'
                : 'var(--color-bg-secondary)',
              border: optInEnabled
                ? '1px solid var(--color-accent)'
                : '1px solid var(--color-border)',
            }}
          >
            <Trophy
              size={14}
              style={{
                color: optInEnabled ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
              }}
            />
            <span
              className="text-xs flex-1 text-left"
              style={{
                color: optInEnabled ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              }}
            >
              {optInEnabled ? 'Sharing Savings' : 'Share Your Savings'}
            </span>
            <span
              className="text-[9px] px-1.5 py-0.5 rounded-full"
              style={{
                background: optInEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary, var(--color-bg-secondary))',
                color: optInEnabled ? 'white' : 'var(--color-text-tertiary)',
              }}
            >
              {optInEnabled ? 'ON' : 'OFF'}
            </span>
          </button>

          <a
            href="https://open-jarvis.github.io/OpenJarvis/leaderboard"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 mt-1.5 px-3 py-1.5 text-[11px] rounded-lg transition-colors"
            style={{ color: 'var(--color-text-tertiary)' }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-accent)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
          >
            <ExternalLink size={10} />
            View Leaderboard
          </a>
        </section>
      </div>
    </div>
  );
}

function MiniStat({
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
      className="rounded-lg px-2.5 py-2"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-1 mb-0.5">
        <Icon size={10} style={{ color: 'var(--color-accent)' }} />
        <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
      </div>
      <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
        {value}
        {unit && (
          <span className="text-[10px] font-normal ml-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
