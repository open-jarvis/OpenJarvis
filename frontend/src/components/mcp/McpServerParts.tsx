import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { McpForm, McpServer, McpTestResult } from '../../lib/mcp-api';

export const inputStyle = {
  background: 'var(--color-bg)',
  border: '1px solid var(--color-border)',
  color: 'var(--color-text)',
};
export const mutedText = { color: 'var(--color-text-tertiary)' };
export const smallButton = 'px-2 py-1 rounded text-[11px] cursor-pointer flex items-center gap-1 disabled:opacity-50';

export function Toggle({ on, onClick, label, disabled }: { on: boolean; onClick: () => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="relative w-9 h-5 rounded-full transition-colors cursor-pointer shrink-0 disabled:opacity-50"
      style={{ background: on ? 'var(--color-accent)' : 'var(--color-bg-tertiary)' }}
    >
      <span
        className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full transition-transform bg-white"
        style={{ transform: on ? 'translateX(16px)' : 'translateX(0)', boxShadow: '0 1px 3px rgba(0,0,0,0.2)' }}
      />
    </button>
  );
}

export function TestResultView({ result }: { result: McpTestResult }) {
  if (!result.ok) {
    return <div className="text-xs mt-2 break-words" style={{ color: 'var(--color-error)' }}>{result.error}</div>;
  }
  const tools = result.tools || [];
  return (
    <div className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
      <div style={{ color: 'var(--color-success)' }}>
        Connected — {tools.length} tool{tools.length === 1 ? '' : 's'}
      </div>
      {tools.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {tools.map((t) => (
            <li key={t.name} style={t.active ? undefined : { ...mutedText, textDecoration: 'line-through' }}>
              <span className="font-mono">{t.name}</span>
              {t.description && <span style={mutedText}> — {t.description}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function serverTarget(server: McpServer): string {
  if (server.transport === 'http') return server.url || '';
  return [server.command, ...server.args].filter(Boolean).join(' ');
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block text-xs mb-3" style={{ color: 'var(--color-text-secondary)' }}>
      <span className="block mb-1">{label}</span>
      {children}
      {hint && <span className="block mt-1 text-[11px]" style={mutedText}>{hint}</span>}
    </label>
  );
}

export function McpServerForm({
  initial,
  editing,
  savedToken,
  onCancel,
  onSave,
  onTest,
}: {
  initial: McpForm;
  editing: boolean;
  savedToken: boolean;
  onCancel: () => void;
  onSave: (form: McpForm) => Promise<void>;
  onTest: (form: McpForm) => Promise<McpTestResult>;
}) {
  const [form, setForm] = useState<McpForm>(initial);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<McpTestResult | null>(null);
  const set = <K extends keyof McpForm>(key: K, value: McpForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const fieldClass = 'w-full px-2 py-1.5 rounded text-xs';

  const run = async (fn: () => Promise<void>, setBusy: (b: boolean) => void) => {
    setError('');
    setBusy(true);
    try {
      await fn();
    } catch (e: any) {
      setError(e?.message || 'Request failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="rounded-lg p-4 mt-3"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      onSubmit={(e) => {
        e.preventDefault();
        void run(() => onSave(form), setSaving);
      }}
    >
      <Field label="Name">
        <input className={fieldClass} style={inputStyle} value={form.name} onChange={(e) => set('name', e.target.value)} required />
      </Field>
      <Field label="Transport">
        <select className={fieldClass} style={inputStyle} value={form.transport} onChange={(e) => set('transport', e.target.value as McpForm['transport'])}>
          <option value="http">Streamable HTTP (URL)</option>
          <option value="stdio">stdio (local command)</option>
        </select>
      </Field>

      {form.transport === 'http' ? (
        <>
          <Field label="URL">
            <input className={fieldClass} style={inputStyle} value={form.url} placeholder="https://host/mcp" onChange={(e) => set('url', e.target.value)} />
          </Field>
          <Field label="Authentication">
            <select className={fieldClass} style={inputStyle} value={form.auth_type} onChange={(e) => set('auth_type', e.target.value as McpForm['auth_type'])}>
              <option value="none">None</option>
              <option value="bearer">Bearer token (Authorization header)</option>
              <option value="header">Token in a custom header</option>
            </select>
          </Field>
          {form.auth_type === 'header' && (
            <Field label="Header name">
              <input className={fieldClass} style={inputStyle} value={form.auth_header} placeholder="X-API-Key" onChange={(e) => set('auth_header', e.target.value)} />
            </Field>
          )}
          {form.auth_type !== 'none' && (
            <Field label="Token" hint="Stored in an owner-only file on the server. It is never shown again.">
              <input
                type="password"
                autoComplete="off"
                className={fieldClass}
                style={inputStyle}
                value={form.token}
                placeholder={savedToken && !form.clearToken ? 'Saved — leave blank to keep' : ''}
                onChange={(e) => set('token', e.target.value)}
              />
              {editing && savedToken && (
                <span className="flex items-center gap-1 mt-1 text-[11px]" style={mutedText}>
                  <input type="checkbox" checked={form.clearToken} onChange={(e) => set('clearToken', e.target.checked)} />
                  Remove saved token
                </span>
              )}
            </Field>
          )}
        </>
      ) : (
        <>
          <Field label="Command">
            <input className={fieldClass} style={inputStyle} value={form.command} placeholder="npx" onChange={(e) => set('command', e.target.value)} />
          </Field>
          <Field label="Arguments" hint="One argument per line. Do not put secrets here; arguments are stored in plain text.">
            <textarea className={`${fieldClass} font-mono`} rows={3} style={inputStyle} value={form.args} onChange={(e) => set('args', e.target.value)} />
          </Field>
        </>
      )}

      <Field label="Only these tools (optional)" hint="Comma-separated tool names. Empty means all tools.">
        <input className={fieldClass} style={inputStyle} value={form.include_tools} onChange={(e) => set('include_tools', e.target.value)} />
      </Field>
      <Field label="Hide these tools (optional)" hint="Comma-separated tool names.">
        <input className={fieldClass} style={inputStyle} value={form.exclude_tools} onChange={(e) => set('exclude_tools', e.target.value)} />
      </Field>
      <div className="flex items-center gap-2 mb-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        <Toggle on={form.enabled} onClick={() => set('enabled', !form.enabled)} label="Enabled" /> Enabled
      </div>

      {error && <div className="text-xs mb-2 break-words" style={{ color: 'var(--color-error)' }}>{error}</div>}
      {result && <TestResultView result={result} />}

      <div className="flex items-center justify-end gap-2 mt-3">
        <button type="button" onClick={onCancel} className={smallButton} style={inputStyle}>Cancel</button>
        <button
          type="button"
          disabled={testing}
          className={smallButton}
          style={inputStyle}
          onClick={() => void run(async () => setResult(await onTest(form)), setTesting)}
        >
          <RefreshCw size={11} className={testing ? 'animate-spin' : undefined} /> Test connection
        </button>
        <button
          type="submit"
          disabled={saving}
          className={smallButton}
          style={{ background: 'var(--color-accent)', color: 'white', border: '1px solid var(--color-accent)' }}
        >
          {editing ? 'Save changes' : 'Add server'}
        </button>
      </div>
    </form>
  );
}

export function RestartNotice() {
  return (
    <div
      role="status"
      className="text-xs rounded-lg px-3 py-2 mb-3"
      style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
    >
      Restart OpenJarvis to apply MCP server changes. Tools are loaded when the server starts.
    </div>
  );
}
