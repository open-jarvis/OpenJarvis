import { useState } from 'react';
import {
  CheckCircle2,
  Circle,
  SkipForward,
  ExternalLink,
  FolderOpen,
  Loader2,
} from 'lucide-react';
import { SOURCE_CATALOG } from '../../types/connectors';
import { connectSource } from '../../lib/connectors-api';
import type { ConnectRequest, ConnectorMeta } from '../../types/connectors';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SourceState = 'pending' | 'connecting' | 'connected' | 'skipped' | 'error';

interface SourceEntry {
  id: string;
  state: SourceState;
  error?: string;
}

// ---------------------------------------------------------------------------
// Sidebar item
// ---------------------------------------------------------------------------

function SidebarItem({
  label,
  state,
  active,
  onClick,
}: {
  label: string;
  state: SourceState;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-left transition-all"
      style={{
        background: active ? 'var(--color-accent-subtle)' : 'transparent',
        border: active ? '1px solid var(--color-accent)' : '1px solid transparent',
      }}
    >
      <div className="shrink-0">
        {state === 'connected' ? (
          <CheckCircle2 size={16} style={{ color: 'var(--color-accent)' }} />
        ) : state === 'connecting' ? (
          <Loader2 size={16} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
        ) : state === 'skipped' ? (
          <SkipForward size={16} style={{ color: 'var(--color-text-tertiary)' }} />
        ) : state === 'error' ? (
          <Circle size={16} style={{ color: '#ef4444' }} />
        ) : (
          <Circle size={16} style={{ color: 'var(--color-text-tertiary)' }} />
        )}
      </div>
      <span
        className="text-sm truncate"
        style={{
          color:
            state === 'skipped'
              ? 'var(--color-text-tertiary)'
              : 'var(--color-text)',
          textDecoration: state === 'skipped' ? 'line-through' : 'none',
        }}
      >
        {label}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Auth panels
// ---------------------------------------------------------------------------

function FilesystemPanel({
  displayName,
  onConnect,
  onSkip,
  isConnecting,
}: {
  displayName: string;
  onConnect: (req: ConnectRequest) => void;
  onSkip: () => void;
  isConnecting: boolean;
}) {
  const [path, setPath] = useState('');
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        Enter the path to your local {displayName} folder.
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="/Users/you/Documents/..."
          className="flex-1 px-3 py-2 rounded-lg text-sm outline-none"
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        />
        <button
          onClick={() => onConnect({ path })}
          disabled={!path.trim() || isConnecting}
          className="px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-all"
          style={{
            background: path.trim() ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
            color: path.trim() ? 'white' : 'var(--color-text-tertiary)',
            cursor: path.trim() && !isConnecting ? 'pointer' : 'not-allowed',
          }}
        >
          {isConnecting ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
          Connect
        </button>
      </div>
      <button
        onClick={onSkip}
        className="text-xs self-start"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        Skip for now
      </button>
    </div>
  );
}

function OAuthPanel({
  displayName,
  authUrl,
  onConnect,
  onSkip,
  isConnecting,
}: {
  displayName: string;
  authUrl?: string;
  onConnect: (req: ConnectRequest) => void;
  onSkip: () => void;
  isConnecting: boolean;
}) {
  const [token, setToken] = useState('');
  const [phase, setPhase] = useState<'start' | 'paste'>('start');

  const openBrowser = () => {
    if (authUrl) {
      window.open(authUrl, '_blank');
    }
    setPhase('paste');
  };

  return (
    <div className="flex flex-col gap-4">
      {phase === 'start' ? (
        <>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Authorize OpenJarvis to access your {displayName} account.
          </p>
          <button
            onClick={openBrowser}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium self-start transition-all"
            style={{
              background: 'var(--color-accent)',
              color: 'white',
            }}
          >
            <ExternalLink size={14} />
            Open in browser
          </button>
        </>
      ) : (
        <>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            After authorizing, paste the token or code below.
          </p>
          <textarea
            value={token}
            onChange={(e) => setToken(e.target.value)}
            rows={3}
            placeholder="Paste auth token or code here..."
            className="w-full px-3 py-2 rounded-lg text-sm outline-none resize-none font-mono"
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
          <div className="flex gap-2">
            <button
              onClick={() => onConnect({ token, code: token })}
              disabled={!token.trim() || isConnecting}
              className="px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-all"
              style={{
                background: token.trim() ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: token.trim() ? 'white' : 'var(--color-text-tertiary)',
                cursor: token.trim() && !isConnecting ? 'pointer' : 'not-allowed',
              }}
            >
              {isConnecting && <Loader2 size={14} className="animate-spin" />}
              Confirm
            </button>
            <button
              onClick={() => setPhase('start')}
              className="px-4 py-2 rounded-lg text-sm font-medium transition-all"
              style={{
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              Back
            </button>
          </div>
        </>
      )}
      <button
        onClick={onSkip}
        className="text-xs self-start"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        Skip for now
      </button>
    </div>
  );
}

function LocalPanel({
  displayName,
  onConnect,
  onSkip,
  isConnecting,
}: {
  displayName: string;
  onConnect: (req: ConnectRequest) => void;
  onSkip: () => void;
  isConnecting: boolean;
}) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        {displayName} reads data directly from your Mac. Make sure the app is installed and
        Full Disk Access is granted to OpenJarvis in System Settings.
      </p>
      <div
        className="px-4 py-3 rounded-lg text-sm"
        style={{
          background: 'var(--color-bg-tertiary)',
          color: 'var(--color-text-secondary)',
        }}
      >
        <strong>System Settings</strong> → Privacy &amp; Security → Full Disk Access →
        enable OpenJarvis
      </div>
      <button
        onClick={() => onConnect({})}
        disabled={isConnecting}
        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium self-start transition-all"
        style={{
          background: 'var(--color-accent)',
          color: 'white',
          cursor: isConnecting ? 'not-allowed' : 'pointer',
          opacity: isConnecting ? 0.7 : 1,
        }}
      >
        {isConnecting && <Loader2 size={14} className="animate-spin" />}
        Check Access
      </button>
      <button
        onClick={onSkip}
        className="text-xs self-start"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        Skip for now
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepByStepPanel — per-connector numbered setup instructions
// ---------------------------------------------------------------------------

function StepByStepPanel({
  connector,
  onConnect,
  onSkip,
  isConnecting,
}: {
  connector: ConnectorMeta;
  onConnect: (req: ConnectRequest) => void;
  onSkip: () => void;
  isConnecting: boolean;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const steps = connector.steps || [];
  const fields = connector.inputFields || [];

  const updateInput = (name: string, value: string) => {
    setInputs((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = () => {
    const req: ConnectRequest = {};
    for (const field of fields) {
      if (field.name === 'email') req.email = inputs.email;
      else if (field.name === 'password') req.password = inputs.password;
      else if (field.name === 'token') req.token = inputs.token;
      else if (field.name === 'path') req.path = inputs.path;
    }
    // For email+password connectors, also set token as email:password
    if (req.email && req.password) {
      req.token = `${req.email}:${req.password}`;
      req.code = req.token;
    }
    if (req.token && !req.code) {
      req.code = req.token;
    }
    onConnect(req);
  };

  const allFilled = fields.every((f) => inputs[f.name]?.trim());

  return (
    <div style={{ padding: '0 4px' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        marginBottom: 16,
      }}>
        <span style={{ fontSize: 20 }}>
          {connector.icon === 'Mail' ? '\u2709\uFE0F' :
           connector.icon === 'Hash' ? '#\uFE0F\u20E3' :
           connector.icon === 'FileText' ? '\uD83D\uDCC4' :
           connector.icon === 'Mic' ? '\uD83C\uDF99\uFE0F' :
           connector.icon === 'FolderOpen' ? '\uD83D\uDCC1' : '\uD83D\uDD17'}
        </span>
        <span style={{ fontWeight: 600, fontSize: 15 }}>
          {connector.display_name}
        </span>
      </div>

      {steps.map((step, i) => (
        <div
          key={i}
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            padding: 12,
            marginBottom: 10,
          }}
        >
          <div style={{
            color: '#7c3aed', fontSize: 11,
            fontWeight: 600, marginBottom: 4,
          }}>
            STEP {i + 1}
          </div>
          <div style={{
            color: 'var(--color-text)',
            fontSize: 13, marginBottom: step.url ? 6 : 0,
          }}>
            {step.label}
          </div>
          {step.url && (
            <a
              href={step.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: '#60a5fa', fontSize: 12,
                textDecoration: 'underline',
              }}
            >
              {step.urlLabel || 'Open'} &rarr;
            </a>
          )}
        </div>
      ))}

      {fields.length > 0 && (
        <div style={{
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 6,
          padding: 12,
          marginBottom: 10,
        }}>
          {fields.map((field) => (
            <input
              key={field.name}
              value={inputs[field.name] || ''}
              onChange={(e) => updateInput(field.name, e.target.value)}
              placeholder={field.placeholder}
              type={field.type || 'text'}
              style={{
                width: '100%',
                padding: '8px 10px',
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                borderRadius: 4,
                color: 'var(--color-text)',
                fontSize: 13,
                marginBottom: 8,
                boxSizing: 'border-box',
              }}
            />
          ))}
        </div>
      )}

      <div style={{
        fontSize: 11, color: 'var(--color-text-secondary)',
        marginBottom: 12, textAlign: 'center',
      }}>
        Read-only access &middot; No data leaves your device
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={handleSubmit}
          disabled={isConnecting || (fields.length > 0 && !allFilled)}
          style={{
            flex: 1, padding: 10,
            background: isConnecting || (fields.length > 0 && !allFilled)
              ? '#444' : '#7c3aed',
            color: 'white', border: 'none',
            borderRadius: 6, fontSize: 13,
            cursor: 'pointer',
          }}
        >
          {isConnecting ? 'Connecting...' : `Connect ${connector.display_name}`}
        </button>
        <button
          onClick={onSkip}
          style={{
            padding: '10px 16px',
            background: 'transparent',
            color: 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
            borderRadius: 6, fontSize: 13,
            cursor: 'pointer',
          }}
        >
          Skip
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SourceConnectFlow
// ---------------------------------------------------------------------------

export function SourceConnectFlow({
  selectedIds,
  onComplete,
}: {
  selectedIds: string[];
  onComplete: () => void;
}) {
  const [entries, setEntries] = useState<SourceEntry[]>(() =>
    selectedIds.map((id) => ({ id, state: 'pending' as SourceState })),
  );
  const [activeIndex, setActiveIndex] = useState(0);

  const updateEntry = (id: string, patch: Partial<SourceEntry>) => {
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  };

  const advanceToNext = (currentIndex: number) => {
    const next = entries.findIndex((e, i) => i > currentIndex && e.state === 'pending');
    if (next !== -1) {
      setActiveIndex(next);
    } else {
      onComplete();
    }
  };

  const handleConnect = async (id: string, req: ConnectRequest) => {
    updateEntry(id, { state: 'connecting', error: undefined });
    try {
      await connectSource(id, req);
      updateEntry(id, { state: 'connected' });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      updateEntry(id, { state: 'error', error: msg });
      return;
    }
    advanceToNext(activeIndex);
  };

  const handleSkip = (id: string) => {
    updateEntry(id, { state: 'skipped' });
    advanceToNext(activeIndex);
  };

  const activeEntry = entries[activeIndex];
  const activeCard = activeEntry
    ? SOURCE_CATALOG.find((c) => c.connector_id === activeEntry.id)
    : null;

  const allDone = entries.every((e) => e.state === 'connected' || e.state === 'skipped');

  return (
    <div className="flex h-full gap-6">
      {/* Sidebar */}
      <div className="w-48 shrink-0 flex flex-col gap-1 py-1">
        <p className="text-xs font-semibold uppercase tracking-wider mb-2"
          style={{ color: 'var(--color-text-tertiary)' }}>
          Sources
        </p>
        {entries.map((entry, idx) => {
          const card = SOURCE_CATALOG.find((c) => c.connector_id === entry.id);
          return (
            <SidebarItem
              key={entry.id}
              label={card?.display_name ?? entry.id}
              state={entry.state}
              active={idx === activeIndex}
              onClick={() => setActiveIndex(idx)}
            />
          );
        })}
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col">
        {activeCard && activeEntry ? (
          <>
            <div className="mb-6">
              <h2 className="text-xl font-bold mb-1" style={{ color: 'var(--color-text)' }}>
                {activeCard.display_name}
              </h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {activeCard.description}
              </p>
              {activeEntry.state === 'error' && activeEntry.error && (
                <div
                  className="mt-3 px-4 py-3 rounded-lg text-sm"
                  style={{
                    background: 'rgba(239,68,68,0.1)',
                    border: '1px solid rgba(239,68,68,0.2)',
                    color: '#ef4444',
                  }}
                >
                  {activeEntry.error}
                </div>
              )}
            </div>

            {activeEntry.state === 'connected' ? (
              <div className="flex items-center gap-2 text-sm"
                style={{ color: 'var(--color-accent)' }}>
                <CheckCircle2 size={18} />
                Connected
              </div>
            ) : activeCard.steps ? (
              <StepByStepPanel
                connector={activeCard}
                onConnect={(req) => handleConnect(activeEntry.id, req)}
                onSkip={() => handleSkip(activeEntry.id)}
                isConnecting={activeEntry.state === 'connecting'}
              />
            ) : activeCard.auth_type === 'filesystem' ? (
              <FilesystemPanel
                displayName={activeCard.display_name}
                onConnect={(req) => handleConnect(activeEntry.id, req)}
                onSkip={() => handleSkip(activeEntry.id)}
                isConnecting={activeEntry.state === 'connecting'}
              />
            ) : activeCard.auth_type === 'local' ? (
              <LocalPanel
                displayName={activeCard.display_name}
                onConnect={(req) => handleConnect(activeEntry.id, req)}
                onSkip={() => handleSkip(activeEntry.id)}
                isConnecting={activeEntry.state === 'connecting'}
              />
            ) : (
              <OAuthPanel
                displayName={activeCard.display_name}
                authUrl={undefined}
                onConnect={(req) => handleConnect(activeEntry.id, req)}
                onSkip={() => handleSkip(activeEntry.id)}
                isConnecting={activeEntry.state === 'connecting'}
              />
            )}
          </>
        ) : (
          <div className="flex flex-col items-center justify-center flex-1 gap-3">
            <CheckCircle2 size={32} style={{ color: 'var(--color-accent)' }} />
            <p className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
              All sources configured
            </p>
          </div>
        )}

        {allDone && (
          <div className="mt-auto pt-4">
            <button
              onClick={onComplete}
              className="w-full py-3 px-4 rounded-xl font-semibold text-sm transition-all"
              style={{ background: 'var(--color-accent)', color: 'white' }}
            >
              Continue →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
