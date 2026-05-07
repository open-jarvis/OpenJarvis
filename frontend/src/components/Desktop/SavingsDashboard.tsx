import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import { invoke } from '@tauri-apps/api/core';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderSavings {
  provider: string;
  label: string;
  input_cost: number;
  output_cost: number;
  total_cost: number;
  energy_wh: number;
  energy_joules: number;
  flops: number;
}

interface SavingsData {
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  local_cost: number;
  per_provider: ProviderSavings[];
  monthly_projection: Record<string, number>;
  session_start_ts: number;
  session_duration_hours: number;
  avg_cost_per_query: Record<string, number>;
  cloud_agent_equivalent: {
    moderate_low: number;
    moderate_high: number;
    heavy_low: number;
    heavy_high: number;
  };
  token_counting_version?: number;
}

// ---------------------------------------------------------------------------
// Styles (Catppuccin)
// ---------------------------------------------------------------------------

const colors = {
  bg: '#1e1e2e',
  surface: '#282840',
  text: '#cdd6f4',
  textMuted: '#a6adc8',
  accent: '#89b4fa',
  green: '#a6e3a1',
  yellow: '#f9e2af',
  red: '#f38ba8',
  purple: '#cba6f7',
  border: '#45475a',
} as const;

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: colors.bg,
    color: colors.text,
    padding: 24,
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    height: '100%',
    overflowY: 'auto',
    boxSizing: 'border-box',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  title: {
    fontSize: 22,
    fontWeight: 600,
    margin: 0,
    color: colors.text,
  },
  liveBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 12,
    color: colors.green,
    background: 'rgba(166,227,161,0.1)',
    padding: '4px 10px',
    borderRadius: 12,
    fontWeight: 500,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: colors.green,
    animation: 'pulse 2s infinite',
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: 16,
    marginBottom: 24,
  },
  statCard: {
    background: colors.surface,
    borderRadius: 10,
    padding: 16,
    border: `1px solid ${colors.border}`,
  },
  statLabel: {
    fontSize: 12,
    color: colors.textMuted,
    marginBottom: 6,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  statValue: {
    fontSize: 26,
    fontWeight: 700,
    color: colors.accent,
    lineHeight: 1.1,
  },
  statUnit: {
    fontSize: 13,
    fontWeight: 400,
    color: colors.textMuted,
    marginLeft: 4,
  },
  sectionHeading: {
    fontSize: 14,
    fontWeight: 600,
    color: colors.textMuted,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: 12,
  },
  providersGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
    gap: 16,
    marginBottom: 24,
  },
  providerCard: {
    background: colors.surface,
    borderRadius: 10,
    padding: 20,
    border: `1px solid ${colors.border}`,
    position: 'relative' as const,
    overflow: 'hidden' as const,
  },
  providerName: {
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 4,
  },
  providerModel: {
    fontSize: 12,
    color: colors.textMuted,
    marginBottom: 14,
  },
  savingsAmount: {
    fontSize: 32,
    fontWeight: 700,
    color: colors.green,
    marginBottom: 8,
  },
  breakdown: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
    marginTop: 14,
    paddingTop: 14,
    borderTop: `1px solid ${colors.border}`,
  },
  breakdownLabel: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
  },
  breakdownValue: {
    fontSize: 16,
    fontWeight: 600,
    marginTop: 2,
  },
  cloudAgentCard: {
    background: colors.surface,
    borderRadius: 10,
    padding: 20,
    border: `1px solid ${colors.border}`,
    borderTop: `3px solid ${colors.purple}`,
    marginBottom: 24,
  },
  cloudAgentGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr 1fr',
    gap: 20,
    marginTop: 16,
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 64,
    color: colors.textMuted,
    gap: 12,
  },
  emptyText: {
    fontSize: 15,
    textAlign: 'center' as const,
  },
  errorBanner: {
    background: 'rgba(243,139,168,0.1)',
    border: `1px solid ${colors.red}`,
    borderRadius: 8,
    padding: '10px 16px',
    marginBottom: 16,
    fontSize: 13,
    color: colors.red,
  },
};

const PROVIDER_COLORS: Record<string, string> = {
  'gpt-5.3': colors.green,
  'claude-opus-4.6': colors.yellow,
  'gemini-3.1-pro': colors.accent,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDollar(n: number): string {
  if (n >= 1000) return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n >= 1) return '$' + n.toFixed(2);
  if (n >= 0.01) return '$' + n.toFixed(3);
  if (n > 0) return '$' + n.toFixed(4);
  return '$0.00';
}

function fmtDuration(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const BLOCKED_WORDS = new Set([
  "ass","asshole","bastard","bitch","bollocks","bullshit","cock","crap",
  "cunt","damn","dick","douchebag","fag","faggot","fuck","fucker","fucking",
  "goddamn","hell","jackass","jerk","motherfucker","nigga","nigger","penis",
  "piss","prick","pussy","retard","shit","slut","twat","vagina","wanker","whore",
]);

function isProfane(text: string): boolean {
  const words = text.toLowerCase().replace(/[^a-z]/g, ' ').split(/\s+/);
  for (const w of words) {
    if (BLOCKED_WORDS.has(w)) return true;
    for (const b of BLOCKED_WORDS) {
      if (w.includes(b)) return true;
    }
  }
  return false;
}

const OPTIN_KEY = 'openjarvis-desktop-optin';
const OPTIN_NAME_KEY = 'openjarvis-desktop-display-name';
const OPTIN_EMAIL_KEY = 'openjarvis-desktop-email';
const OPTIN_ANONID_KEY = 'openjarvis-desktop-anon-id';

function getOrCreateAnonId(): string {
  const stored = localStorage.getItem(OPTIN_ANONID_KEY);
  if (stored) return stored;
  const id = crypto.randomUUID();
  localStorage.setItem(OPTIN_ANONID_KEY, id);
  return id;
}

const SUPABASE_URL = 'https://mtbtgpwzrbostweaanpr.supabase.co';
const SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im10YnRncHd6cmJvc3R3ZWFhbnByIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMxODk0OTQsImV4cCI6MjA4ODc2NTQ5NH0._xMlqCfljtXpwPj54H-ghxfLFO-jiq4W2WhpU8vVL1c';

const REFRESH_INTERVAL_MS = 5000;

export function SavingsDashboard({ apiUrl }: { apiUrl: string }) {
  const [data, setData] = useState<SavingsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [optInEnabled, setOptInEnabled] = useState(localStorage.getItem(OPTIN_KEY) === 'true');
  const [displayName, setDisplayName] = useState(localStorage.getItem(OPTIN_NAME_KEY) || '');
  const [emailStored, setEmailStored] = useState(localStorage.getItem(OPTIN_EMAIL_KEY) || '');
  const [nameInput, setNameInput] = useState(localStorage.getItem(OPTIN_NAME_KEY) || '');
  const [emailInput, setEmailInput] = useState(localStorage.getItem(OPTIN_EMAIL_KEY) || '');
  const [nameError, setNameError] = useState('');
  const [showOptIn, setShowOptIn] = useState(false);
  const anonId = getOrCreateAnonId();

  const fetchData = useCallback(async () => {
    try {
      const result = await invoke<SavingsData>('fetch_savings', { apiUrl });
      setData(result);
      setError(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchData]);

  // Share savings to Supabase when opted in and data changes
  useEffect(() => {
    if (!optInEnabled || !displayName || !data) return;
    const dollarSavings = data.per_provider.reduce((s, p) => s + p.total_cost, 0);
    const energySaved = data.per_provider.reduce((s, p) => s + (p.energy_wh || 0), 0);
    const flopsSaved = data.per_provider.reduce((s, p) => s + (p.flops || 0), 0);
    invoke('submit_savings', {
      supabaseUrl: SUPABASE_URL,
      supabaseKey: SUPABASE_KEY,
      payload: {
        anon_id: anonId,
        display_name: displayName,
        email: emailStored,
        total_calls: data.total_calls,
        total_tokens: data.total_tokens,
        dollar_savings: dollarSavings,
        energy_wh_saved: energySaved,
        flops_saved: flopsSaved,
        token_counting_version: data.token_counting_version ?? 1,
      },
    }).catch(() => {});
  }, [data, optInEnabled, displayName, anonId]);

  const handleOptInJoin = () => {
    const trimmed = nameInput.trim();
    const trimmedEmail = emailInput.trim();
    if (!trimmed || trimmed.length < 2 || trimmed.length > 30) {
      setNameError('Name must be 2-30 characters');
      return;
    }
    if (isProfane(trimmed)) {
      setNameError('Please choose a different name');
      return;
    }
    if (!trimmedEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setNameError('Please enter a valid email address');
      return;
    }
    setNameError('');
    localStorage.setItem(OPTIN_KEY, 'true');
    localStorage.setItem(OPTIN_NAME_KEY, trimmed);
    localStorage.setItem(OPTIN_EMAIL_KEY, trimmedEmail);
    setOptInEnabled(true);
    setDisplayName(trimmed);
    setEmailStored(trimmedEmail);
    setShowOptIn(false);
  };

  const handleOptOut = () => {
    localStorage.removeItem(OPTIN_KEY);
    localStorage.removeItem(OPTIN_NAME_KEY);
    localStorage.removeItem(OPTIN_EMAIL_KEY);
    setOptInEnabled(false);
    setDisplayName('');
    setEmailStored('');
    setShowOptIn(false);
  };

  if (!loading && !data && !error) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <h2 style={styles.title}>Savings Dashboard</h2>
        </div>
        <div style={styles.emptyState}>
          <div style={{ fontSize: 40, opacity: 0.4 }}>$</div>
          <div style={styles.emptyText}>
            No savings data available.<br />
            Start making inference requests to see savings vs cloud providers.
          </div>
        </div>
      </div>
    );
  }

  const providers = data?.per_provider ?? [];
  const projection = data?.monthly_projection ?? {};
  const cloudAgent = data?.cloud_agent_equivalent;

  return (
    <div style={styles.container}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>

      {/* Header */}
      <div style={styles.header}>
        <h2 style={styles.title}>Savings Dashboard</h2>
        <span style={styles.liveBadge}>
          <span style={styles.liveDot} />
          Live - {REFRESH_INTERVAL_MS / 1000}s
        </span>
      </div>

      {error && <div style={styles.errorBanner}>{error}</div>}

      {/* Leaderboard Opt-in */}
      {showOptIn ? (
        <div style={{ ...styles.statCard, marginBottom: 24, padding: 20 }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: colors.text }}>
            Share Your Savings
          </div>
          <div style={{ fontSize: 13, color: colors.textMuted, marginBottom: 14, lineHeight: 1.5 }}>
            Opt in to privately share your savings for the chance to win a Mac Mini!
          </div>
          <div style={{ marginBottom: 8 }}>
            <input
              type="text"
              value={nameInput}
              onChange={(e) => { setNameInput(e.target.value); setNameError(''); }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleOptInJoin(); }}
              placeholder="Display name for leaderboard"
              maxLength={30}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: 8,
                background: colors.bg,
                border: `1px solid ${colors.border}`,
                color: colors.text,
                fontSize: 14,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: colors.textMuted, marginBottom: 4 }}>
              Email <span style={{ color: colors.red }}>*</span>
              <span style={{ fontWeight: 400, marginLeft: 4, opacity: 0.7 }}>(never shown publicly)</span>
            </div>
            <input
              type="email"
              value={emailInput}
              onChange={(e) => { setEmailInput(e.target.value); setNameError(''); }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleOptInJoin(); }}
              placeholder="your@email.com"
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: 8,
                background: colors.bg,
                border: `1px solid ${colors.border}`,
                color: colors.text,
                fontSize: 14,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            {nameError && (
              <div style={{ fontSize: 12, color: colors.red, marginTop: 4 }}>{nameError}</div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleOptInJoin}
              style={{
                padding: '8px 18px',
                borderRadius: 8,
                background: colors.accent,
                color: '#1e1e2e',
                fontWeight: 600,
                fontSize: 13,
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Join Leaderboard
            </button>
            <button
              onClick={() => setShowOptIn(false)}
              style={{
                padding: '8px 14px',
                borderRadius: 8,
                background: 'transparent',
                color: colors.textMuted,
                fontSize: 13,
                border: `1px solid ${colors.border}`,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            {optInEnabled && (
              <button
                onClick={handleOptOut}
                style={{
                  padding: '8px 14px',
                  borderRadius: 8,
                  background: 'transparent',
                  color: colors.red,
                  fontSize: 13,
                  border: `1px solid ${colors.border}`,
                  cursor: 'pointer',
                  marginLeft: 'auto',
                }}
              >
                Opt Out
              </button>
            )}
          </div>
        </div>
      ) : (
        <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={() => setShowOptIn(true)}
            style={{
              padding: '6px 14px',
              borderRadius: 8,
              background: optInEnabled ? 'rgba(166,227,161,0.15)' : colors.surface,
              border: optInEnabled ? `1px solid ${colors.green}` : `1px solid ${colors.border}`,
              color: optInEnabled ? colors.green : colors.textMuted,
              fontSize: 12,
              fontWeight: 500,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            {optInEnabled ? `Sharing as "${displayName}"` : 'Share Your Savings'}
          </button>
          <a
            href="https://open-jarvis.github.io/OpenJarvis/leaderboard"
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 12, color: colors.accent, textDecoration: 'none' }}
          >
            View Leaderboard ↗
          </a>
        </div>
      )}

      {/* Stat cards row */}
      <div style={styles.statsGrid}>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>Total Requests</div>
          <div style={styles.statValue}>
            {(data?.total_calls ?? 0).toLocaleString()}
          </div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>Total Tokens</div>
          <div style={styles.statValue}>
            {(data?.total_tokens ?? 0).toLocaleString()}
          </div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>Session Duration</div>
          <div style={styles.statValue}>
            {fmtDuration(data?.session_duration_hours ?? 0)}
          </div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>Local Cost</div>
          <div style={{ ...styles.statValue, color: colors.green }}>
            {fmtDollar(data?.local_cost ?? 0)}
          </div>
        </div>
      </div>

      {/* Provider savings cards */}
      <div style={styles.sectionHeading}>Savings vs Cloud Providers*</div>
      <div style={styles.providersGrid}>
        {providers.map((p) => (
          <div
            key={p.provider}
            style={{
              ...styles.providerCard,
              borderTop: `3px solid ${PROVIDER_COLORS[p.provider] ?? colors.accent}`,
            }}
          >
            <div style={styles.providerName}>{p.label}</div>
            <div style={styles.providerModel}>{p.provider}</div>
            <div style={styles.savingsAmount}>{fmtDollar(p.total_cost)}</div>
            <div style={styles.breakdown}>
              <div>
                <div style={styles.breakdownLabel}>Input Saved</div>
                <div style={styles.breakdownValue}>{fmtDollar(p.input_cost)}</div>
              </div>
              <div>
                <div style={styles.breakdownLabel}>Output Saved</div>
                <div style={styles.breakdownValue}>{fmtDollar(p.output_cost)}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: colors.textMuted, marginTop: 8, lineHeight: 1.5 }}>
        *Savings estimates assume local models (e.g. Qwen, Nemotron, Kimi) produce roughly the same number of tokens per request, on average, as closed-source cloud models.
      </div>

      {/* Cloud Agent Platforms */}
      {cloudAgent && (
        <>
          <div style={styles.sectionHeading}>vs Cloud Agent Platforms</div>
          <div style={styles.cloudAgentCard}>
            <div style={styles.providerName}>Typical Cloud Agent Platform</div>
            <div style={styles.providerModel}>based on published API pricing tiers</div>
            <div style={styles.cloudAgentGrid}>
              <div>
                <div style={styles.breakdownLabel}>MODERATE USE</div>
                <div style={{ ...styles.breakdownValue, color: colors.yellow, fontSize: 20 }}>
                  ${cloudAgent.moderate_low}&ndash;{cloudAgent.moderate_high}/mo
                </div>
              </div>
              <div>
                <div style={styles.breakdownLabel}>HEAVY USE</div>
                <div style={{ ...styles.breakdownValue, color: colors.red, fontSize: 20 }}>
                  ${cloudAgent.heavy_low}&ndash;{cloudAgent.heavy_high}+/mo
                </div>
              </div>
              <div>
                <div style={styles.breakdownLabel}>YOUR COST</div>
                <div style={{ ...styles.breakdownValue, color: colors.green, fontSize: 24 }}>
                  $0.00
                </div>
                <div style={{ fontSize: 12, color: colors.textMuted, marginTop: 2 }}>
                  local inference
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Monthly Projection */}
      <div style={styles.sectionHeading}>Monthly Projection</div>
      <div style={styles.providersGrid}>
        {providers.map((p) => (
          <div
            key={`proj-${p.provider}`}
            style={{
              ...styles.providerCard,
              borderTop: `3px solid ${PROVIDER_COLORS[p.provider] ?? colors.accent}`,
            }}
          >
            <div style={styles.providerName}>vs {p.label}</div>
            <div style={styles.providerModel}>projected monthly savings</div>
            <div style={styles.savingsAmount}>
              {fmtDollar(projection[p.provider] ?? 0)}
            </div>
            <div style={{ fontSize: 12, color: colors.textMuted }}>
              per month at current rate
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
