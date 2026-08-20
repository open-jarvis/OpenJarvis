import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import { invoke } from '@tauri-apps/api/core';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PolicyConfig {
  name: string;
  enabled: boolean;
  update_interval: number;
}

interface RoutingWeight {
  query_class: string;
  model: string;
  weight: number;
}

interface BanditArm {
  model: string;
  pulls: number;
  reward_mean: number;
  ucb: number;
}

interface LearningStatsPoint {
  timestamp: string;
  accuracy: number;
  latency_ms: number;
  cost: number;
}

interface LearningStats {
  history: LearningStatsPoint[];
  icl_example_count: number;
  discovered_skills_count: number;
  total_traces: number;
  total_updates: number;
}

interface LearningPolicy {
  config: PolicyConfig;
  routing_weights: RoutingWeight[];
  bandit_arms: BanditArm[];
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: '#1e1e2e',
    color: '#cdd6f4',
    padding: 24,
    borderRadius: 12,
    fontFamily: 'system-ui, -apple-system, sans-serif',
    minHeight: 400,
  },
  header: {
    fontSize: 20,
    fontWeight: 700,
    marginBottom: 20,
    color: '#cdd6f4',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: 16,
    marginBottom: 24,
  },
  card: {
    backgroundColor: '#313244',
    borderRadius: 8,
    padding: 16,
  },
  cardTitle: {
    fontSize: 13,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    color: '#89b4fa',
    marginBottom: 12,
  },
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '4px 0',
  },
  label: {
    fontSize: 13,
    color: '#a6adc8',
  },
  value: {
    fontSize: 13,
    fontWeight: 500,
    color: '#cdd6f4',
  },
  badge: {
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 12,
    fontWeight: 600,
  },
  badgeEnabled: {
    backgroundColor: '#a6e3a133',
    color: '#a6e3a1',
  },
  badgeDisabled: {
    backgroundColor: '#f3858833',
    color: '#f38588',
  },
  chartContainer: {
    backgroundColor: '#313244',
    borderRadius: 8,
    padding: 16,
    marginBottom: 24,
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 13,
  },
  th: {
    textAlign: 'left' as const,
    padding: '6px 8px',
    borderBottom: '1px solid #45475a',
    color: '#89b4fa',
    fontWeight: 600,
    fontSize: 12,
    textTransform: 'uppercase' as const,
  },
  td: {
    padding: '6px 8px',
    borderBottom: '1px solid #313244',
    color: '#cdd6f4',
  },
  weightBar: {
    height: 6,
    borderRadius: 3,
    backgroundColor: '#45475a',
    overflow: 'hidden' as const,
    marginTop: 4,
  },
  weightFill: {
    height: '100%',
    borderRadius: 3,
    backgroundColor: '#89b4fa',
  },
  error: {
    color: '#f38588',
    padding: 12,
    backgroundColor: '#f3858811',
    borderRadius: 8,
    fontSize: 13,
  },
  loading: {
    color: '#a6adc8',
    textAlign: 'center' as const,
    padding: 40,
  },
  statNumber: {
    fontSize: 28,
    fontWeight: 700,
    color: '#89b4fa',
    lineHeight: 1.2,
  },
  statLabel: {
    fontSize: 12,
    color: '#a6adc8',
    marginTop: 4,
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LearningCurve({ apiUrl }: { apiUrl: string }) {
  const [stats, setStats] = useState<LearningStats | null>(null);
  const [policy, setPolicy] = useState<LearningPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [statsResult, policyResult] = await Promise.all([
        invoke<LearningStats>('fetch_learning_stats', { apiUrl }),
        invoke<LearningPolicy>('fetch_learning_policy', { apiUrl }),
      ]);
      setStats(statsResult);
      setPolicy(policyResult);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  if (loading && !stats) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>Loading learning data...</div>
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>Learning Curve</div>
        <div style={styles.error}>{error}</div>
      </div>
    );
  }

  const chartData = (stats?.history ?? []).map((point) => ({
    time: point.timestamp,
    accuracy: Math.round(point.accuracy * 1000) / 10,
    latency: Math.round(point.latency_ms),
    cost: Math.round(point.cost * 10000) / 10000,
  }));

  const policyConfig = policy?.config;
  const isGrpo = policyConfig?.name?.toLowerCase().includes('grpo');
  const isBandit = policyConfig?.name?.toLowerCase().includes('bandit');

  return (
    <div style={styles.container}>
      <div style={styles.header}>Learning Curve</div>

      {error && <div style={styles.error}>{error}</div>}

      {/* Policy config + counters */}
      <div style={styles.grid}>
        <div style={styles.card}>
          <div style={styles.cardTitle}>Policy Config</div>
          <div style={styles.row}>
            <span style={styles.label}>Policy</span>
            <span style={styles.value}>{policyConfig?.name ?? 'unknown'}</span>
          </div>
          <div style={styles.row}>
            <span style={styles.label}>Status</span>
            <span
              style={{
                ...styles.badge,
                ...(policyConfig?.enabled ? styles.badgeEnabled : styles.badgeDisabled),
              }}
            >
              {policyConfig?.enabled ? 'Enabled' : 'Disabled'}
            </span>
          </div>
          <div style={styles.row}>
            <span style={styles.label}>Update interval</span>
            <span style={styles.value}>{policyConfig?.update_interval ?? 0}s</span>
          </div>
        </div>

        <div style={styles.card}>
          <div style={styles.cardTitle}>Counters</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <div style={styles.statNumber}>{stats?.total_traces ?? 0}</div>
              <div style={styles.statLabel}>Total traces</div>
            </div>
            <div>
              <div style={styles.statNumber}>{stats?.total_updates ?? 0}</div>
              <div style={styles.statLabel}>Policy updates</div>
            </div>
            <div>
              <div style={styles.statNumber}>{stats?.icl_example_count ?? 0}</div>
              <div style={styles.statLabel}>ICL examples</div>
            </div>
            <div>
              <div style={styles.statNumber}>{stats?.discovered_skills_count ?? 0}</div>
              <div style={styles.statLabel}>Discovered skills</div>
            </div>
          </div>
        </div>
      </div>

      {/* Accuracy / latency chart */}
      {chartData.length > 0 && (
        <div style={styles.chartContainer}>
          <div style={styles.cardTitle}>Routing Accuracy Over Time</div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#45475a" />
              <XAxis
                dataKey="time"
                tick={{ fill: '#a6adc8', fontSize: 11 }}
                stroke="#45475a"
              />
              <YAxis
                yAxisId="left"
                tick={{ fill: '#a6adc8', fontSize: 11 }}
                stroke="#45475a"
                label={{
                  value: 'Accuracy %',
                  angle: -90,
                  position: 'insideLeft',
                  style: { fill: '#a6adc8', fontSize: 11 },
                }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fill: '#a6adc8', fontSize: 11 }}
                stroke="#45475a"
                label={{
                  value: 'Latency (ms)',
                  angle: 90,
                  position: 'insideRight',
                  style: { fill: '#a6adc8', fontSize: 11 },
                }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#313244',
                  border: '1px solid #45475a',
                  borderRadius: 6,
                  color: '#cdd6f4',
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ color: '#cdd6f4', fontSize: 12 }} />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="accuracy"
                name="Accuracy %"
                stroke="#89b4fa"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="latency"
                name="Latency (ms)"
                stroke="#f9e2af"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* GRPO routing weights */}
      {isGrpo && (policy?.routing_weights ?? []).length > 0 && (
        <div style={styles.card}>
          <div style={styles.cardTitle}>GRPO Routing Weights</div>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Query Class</th>
                <th style={styles.th}>Model</th>
                <th style={styles.th}>Weight</th>
              </tr>
            </thead>
            <tbody>
              {policy!.routing_weights.map((rw, i) => (
                <tr key={i}>
                  <td style={styles.td}>{rw.query_class}</td>
                  <td style={styles.td}>{rw.model}</td>
                  <td style={styles.td}>
                    <span>{(rw.weight * 100).toFixed(1)}%</span>
                    <div style={styles.weightBar}>
                      <div
                        style={{
                          ...styles.weightFill,
                          width: `${Math.min(rw.weight * 100, 100)}%`,
                        }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Bandit arm stats */}
      {isBandit && (policy?.bandit_arms ?? []).length > 0 && (
        <div style={{ ...styles.card, marginTop: 16 }}>
          <div style={styles.cardTitle}>Bandit Arm Statistics</div>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Model</th>
                <th style={styles.th}>Pulls</th>
                <th style={styles.th}>Mean Reward</th>
                <th style={styles.th}>UCB</th>
              </tr>
            </thead>
            <tbody>
              {policy!.bandit_arms.map((arm, i) => (
                <tr key={i}>
                  <td style={styles.td}>{arm.model}</td>
                  <td style={styles.td}>{arm.pulls}</td>
                  <td style={styles.td}>{arm.reward_mean.toFixed(4)}</td>
                  <td style={styles.td}>{arm.ucb.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
