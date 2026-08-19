import { Table2 } from 'lucide-react';
import type { ScienceComparisonRow, ScienceSimulationResult } from '../../lib/api';

const NOT_AVAILABLE = 'N/A — dados insuficientes';

function basisColor(basis: string): string {
  if (basis === 'DADO EXPERIMENTAL') return 'var(--color-success)';
  if (basis === 'VALOR CALCULADO') return 'var(--color-accent)';
  if (basis === 'ESTIMATIVA') return 'var(--color-warning)';
  return 'var(--color-text-tertiary)'; // HIPÓTESE
}

export function ComparisonTable({ rows }: { rows: ScienceComparisonRow[] }) {
  if (!rows.length) return null;
  const properties = Array.from(
    new Set(rows.flatMap((r) => Object.keys(r.properties))),
  );

  return (
    <div className="hud-panel p-4">
      <div className="hud-label mb-3 flex items-center gap-2">
        <Table2 size={12} style={{ color: 'var(--color-accent)' }} />
        COMPARE MATERIALS
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm hud-mono" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
              <th className="text-left py-2 pr-4" style={{ color: 'var(--color-text-tertiary)' }}>
                Material
              </th>
              {properties.map((p) => (
                <th key={p} className="text-left py-2 pr-4" style={{ color: 'var(--color-text-tertiary)' }}>
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.material} style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
                <td className="py-2 pr-4 font-medium" style={{ color: 'var(--color-text)' }}>
                  {row.material}
                </td>
                {properties.map((p) => {
                  const value = row.properties[p] ?? NOT_AVAILABLE;
                  return (
                    <td
                      key={p}
                      className="py-2 pr-4"
                      style={{ color: value === NOT_AVAILABLE ? 'var(--color-text-tertiary)' : 'var(--color-text-secondary)' }}
                    >
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SimulationList({ simulations }: { simulations: ScienceSimulationResult[] }) {
  if (!simulations.length) return null;
  return (
    <div className="hud-panel p-4">
      <div className="hud-label mb-3">SIMULAÇÕES</div>
      <div className="flex flex-col gap-2">
        {simulations.map((s, i) => (
          <div key={`${s.quantity}-${i}`} className="flex items-center justify-between text-sm hud-mono">
            <span style={{ color: 'var(--color-text)' }}>
              {s.quantity} = {s.value} {s.unit}
            </span>
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{
                color: basisColor(s.basis),
                border: `1px solid ${basisColor(s.basis)}`,
              }}
            >
              {s.basis}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
