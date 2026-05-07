import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import { invoke } from '@tauri-apps/api/core';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HealthStatus {
  status: string;
}

interface AgentInfo {
  name: string;
  key: string;
  accepts_tools: boolean;
  description: string;
}

interface AgentsResponse {
  agents: AgentInfo[];
}

interface ServerInfo {
  model: string;
  agent: string;
  engine: string;
  version: string;
  uptime_seconds: number;
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
    padding: '6px 0',
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
  healthDot: {
    display: 'inline-block',
    width: 10,
    height: 10,
    borderRadius: '50%',
    marginRight: 8,
    verticalAlign: 'middle',
  },
  healthDotHealthy: {
    backgroundColor: '#a6e3a1',
    boxShadow: '0 0 6px #a6e3a166',
  },
  healthDotUnhealthy: {
    backgroundColor: '#f38588',
    boxShadow: '0 0 6px #f3858866',
  },
  healthDotUnknown: {
    backgroundColor: '#a6adc8',
  },
  badge: {
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 12,
    fontWeight: 600,
  },
  badgeTrue: {
    backgroundColor: '#a6e3a133',
    color: '#a6e3a1',
  },
  badgeFalse: {
    backgroundColor: '#45475a',
    color: '#a6adc8',
  },
  agentTable: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 13,
  },
  th: {
    textAlign: 'left' as const,
    padding: '8px 10px',
    borderBottom: '1px solid #45475a',
    color: '#89b4fa',
    fontWeight: 600,
    fontSize: 12,
    textTransform: 'uppercase' as const,
  },
  td: {
    padding: '8px 10px',
    borderBottom: '1px solid #313244',
    color: '#cdd6f4',
  },
  buttonGroup: {
    display: 'flex',
    gap: 10,
    marginTop: 16,
  },
  button: {
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 600,
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
  },
  startButton: {
    backgroundColor: '#a6e3a1',
    color: '#1e1e2e',
  },
  stopButton: {
    backgroundColor: '#f38588',
    color: '#1e1e2e',
  },
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  error: {
    color: '#f38588',
    padding: 12,
    backgroundColor: '#f3858811',
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 16,
  },
  commandOutput: {
    marginTop: 12,
    padding: 12,
    backgroundColor: '#181825',
    borderRadius: 6,
    fontSize: 12,
    fontFamily: 'monospace',
    color: '#a6adc8',
    maxHeight: 120,
    overflow: 'auto',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
  },
  loading: {
    color: '#a6adc8',
    textAlign: 'center' as const,
    padding: 40,
  },
  healthStatus: {
    display: 'flex',
    alignItems: 'center',
    fontSize: 16,
    fontWeight: 600,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AdminPanel({ apiUrl }: { apiUrl: string }) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [commandRunning, setCommandRunning] = useState(false);
  const [commandOutput, setCommandOutput] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      // Check health
      const healthResult = await invoke<HealthStatus>('check_health', { apiUrl });
      setHealthy(healthResult.status === 'ok');

      // Fetch agents
      try {
        const agentsResult = await invoke<AgentsResponse>('fetch_agents', { apiUrl });
        setAgents(agentsResult.agents ?? []);
      } catch {
        // Agent list may not be available; keep previous state
      }

      // Fetch server info (model, engine, uptime)
      try {
        const infoResult = await invoke<ServerInfo>('check_health', { apiUrl });
        // If server exposes extra fields, merge them
        setServerInfo((prev) => ({
          model: prev?.model ?? '',
          agent: prev?.agent ?? '',
          engine: prev?.engine ?? '',
          version: prev?.version ?? '',
          uptime_seconds: prev?.uptime_seconds ?? 0,
          ...infoResult as unknown as Partial<ServerInfo>,
        }));
      } catch {
        // Non-critical
      }

      setError(null);
    } catch (err) {
      setHealthy(false);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleStart = useCallback(async () => {
    setCommandRunning(true);
    setCommandOutput(null);
    try {
      const output = await invoke<string>('run_jarvis_command', {
        args: ['serve', '--port', '8000'],
      });
      setCommandOutput(output);
      // Wait a moment then refresh health
      setTimeout(refresh, 2000);
    } catch (err) {
      setCommandOutput(err instanceof Error ? err.message : String(err));
    } finally {
      setCommandRunning(false);
    }
  }, [refresh]);

  const handleStop = useCallback(async () => {
    setCommandRunning(true);
    setCommandOutput(null);
    try {
      const output = await invoke<string>('run_jarvis_command', {
        args: ['stop'],
      });
      setCommandOutput(output);
      setTimeout(refresh, 2000);
    } catch (err) {
      setCommandOutput(err instanceof Error ? err.message : String(err));
    } finally {
      setCommandRunning(false);
    }
  }, [refresh]);

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>Loading system status...</div>
      </div>
    );
  }

  const healthDotStyle =
    healthy === null
      ? styles.healthDotUnknown
      : healthy
        ? styles.healthDotHealthy
        : styles.healthDotUnhealthy;

  const healthLabel =
    healthy === null ? 'Unknown' : healthy ? 'Healthy' : 'Unhealthy';

  return (
    <div style={styles.container}>
      <div style={styles.header}>Admin Panel</div>

      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.grid}>
        {/* Health & Engine */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>System Health</div>
          <div style={{ ...styles.row, marginBottom: 8 }}>
            <div style={styles.healthStatus}>
              <span style={{ ...styles.healthDot, ...healthDotStyle }} />
              {healthLabel}
            </div>
          </div>
          <div style={styles.row}>
            <span style={styles.label}>Engine</span>
            <span style={styles.value}>{serverInfo?.engine || 'N/A'}</span>
          </div>
          <div style={styles.row}>
            <span style={styles.label}>Model</span>
            <span style={styles.value}>{serverInfo?.model || 'N/A'}</span>
          </div>
          <div style={styles.row}>
            <span style={styles.label}>Agent</span>
            <span style={styles.value}>{serverInfo?.agent || 'N/A'}</span>
          </div>
        </div>

        {/* System Info */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>System Info</div>
          <div style={styles.row}>
            <span style={styles.label}>Version</span>
            <span style={styles.value}>{serverInfo?.version || '0.1.0'}</span>
          </div>
          <div style={styles.row}>
            <span style={styles.label}>Uptime</span>
            <span style={styles.value}>
              {serverInfo?.uptime_seconds !== undefined
                ? formatUptime(serverInfo.uptime_seconds)
                : 'N/A'}
            </span>
          </div>
          <div style={styles.row}>
            <span style={styles.label}>API URL</span>
            <span style={styles.value}>{apiUrl}</span>
          </div>

          {/* Server controls */}
          <div style={styles.buttonGroup}>
            <button
              style={{
                ...styles.button,
                ...styles.startButton,
                ...(commandRunning ? styles.buttonDisabled : {}),
              }}
              onClick={handleStart}
              disabled={commandRunning}
            >
              Start Server
            </button>
            <button
              style={{
                ...styles.button,
                ...styles.stopButton,
                ...(commandRunning ? styles.buttonDisabled : {}),
              }}
              onClick={handleStop}
              disabled={commandRunning}
            >
              Stop Server
            </button>
          </div>

          {commandOutput && (
            <div style={styles.commandOutput}>{commandOutput}</div>
          )}
        </div>
      </div>

      {/* Agent Registry */}
      {agents.length > 0 && (
        <div style={styles.card}>
          <div style={styles.cardTitle}>Agent Registry ({agents.length})</div>
          <table style={styles.agentTable}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Key</th>
                <th style={styles.th}>Tools</th>
                <th style={styles.th}>Description</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr key={agent.key}>
                  <td style={styles.td}>{agent.name}</td>
                  <td style={{ ...styles.td, fontFamily: 'monospace', fontSize: 12 }}>
                    {agent.key}
                  </td>
                  <td style={styles.td}>
                    <span
                      style={{
                        ...styles.badge,
                        ...(agent.accepts_tools ? styles.badgeTrue : styles.badgeFalse),
                      }}
                    >
                      {agent.accepts_tools ? 'Yes' : 'No'}
                    </span>
                  </td>
                  <td style={{ ...styles.td, color: '#a6adc8', fontSize: 12 }}>
                    {agent.description || '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {agents.length === 0 && !loading && (
        <div style={styles.card}>
          <div style={styles.cardTitle}>Agent Registry</div>
          <div style={{ color: '#a6adc8', fontSize: 13, padding: '8px 0' }}>
            No agents registered or server not reachable.
          </div>
        </div>
      )}
    </div>
  );
}
