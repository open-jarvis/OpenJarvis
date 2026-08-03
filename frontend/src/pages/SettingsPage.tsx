import { useState, useEffect, useCallback } from 'react';
import {
  Palette,
  Globe,
  Cpu,
  Database,
  Info,
  Check,
  Sun,
  Moon,
  Monitor,
  Download,
  Upload,
  Trash2,
  Mic,
  Key,
  Search,
  Brain,
  RefreshCw,
  Plus,
  Plug,
  Shield,
  Square,
} from 'lucide-react';
import { useAppStore, type ThemeMode } from '../lib/store';
import {
  checkHealth,
  fetchSpeechHealth,
  getMemoryStats,
  getInferenceSource,
  setInferenceSource,
  getCloudKeyStatus,
  saveCloudKey,
  isTauri,
  type InferenceSource,
  fetchMcpStatus,
  saveMcpServer,
  removeMcpServer,
  reconnectMcpServer,
  fetchDesktopStatus,
  saveDesktopTarget,
  connectDesktopTarget,
  interruptDesktop,
  type McpServerInput,
  type McpServerStatus,
  type McpToolStatus,
  type DesktopStatus,
} from '../lib/api';
import { isAutoUpdateDisabled, setAutoUpdateDisabled } from '../components/Desktop/UpdateChecker';

const CLOUD_KEY_STATUS_CHANGED = 'openjarvis-cloud-key-status-changed';

function OllamaModelList() {
  const [models, setModels] = useState<Array<{ name: string; size: number }>>([]);
  useEffect(() => {
    fetch('http://localhost:11434/api/tags')
      .then(r => r.json())
      .then(data => setModels((data.models || []).map((m: any) => ({ name: m.name, size: m.size }))))
      .catch(() => setModels([]));
  }, []);
  if (models.length === 0) return <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No models loaded</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {models.map(m => (
        <span key={m.name} className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px]"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-success)', display: 'inline-block' }} />
          {m.name} ({(m.size / 1e9).toFixed(1)} GB)
        </span>
      ))}
    </div>
  );
}

function ApiKeyInput({ keyName, placeholder }: { keyName: string; placeholder: string }) {
  const [value, setValue] = useState('');
  const [saved, setSaved] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const [error, setError] = useState('');
  const desktopKeyStorage = isTauri();

  const refresh = useCallback(async () => {
    if (!desktopKeyStorage) {
      setHasKey(false);
      return;
    }
    try {
      const status = await getCloudKeyStatus();
      setHasKey(!!status[keyName]);
    } catch {
      setHasKey(false);
    }
  }, [desktopKeyStorage, keyName]);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  const save = async (v: string) => {
    const next = v.trim();
    if (!next) return;
    setError('');
    try {
      await saveCloudKey(keyName, next);
      setValue('');
      setHasKey(true);
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || 'Failed to save API key');
    }
  };

  const remove = async () => {
    setError('');
    try {
      await saveCloudKey(keyName, '');
      setValue('');
      setHasKey(false);
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || 'Failed to remove API key');
    }
  };

  return (
    <div className="flex items-center gap-2">
      <input
        type="password"
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={() => { if (value.trim()) void save(value); }}
        placeholder={hasKey ? 'Saved in secure storage' : placeholder}
        disabled={!desktopKeyStorage}
        className="w-48 px-2 py-1 rounded text-xs"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
      {hasKey && (
        <button
          onClick={() => void remove()}
          className="px-2 py-1 rounded text-[10px] cursor-pointer"
          style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
        >
          Remove
        </button>
      )}
      {saved && <span className="text-[10px]" style={{ color: 'var(--color-success)' }}>Saved</span>}
      {error && <span className="text-[10px]" style={{ color: 'var(--color-error)' }}>{error}</span>}
    </div>
  );
}

function CloudProviderStatus({ label, keyName }: { label: string; keyName: string }) {
  const [hasKey, setHasKey] = useState(false);
  const desktopKeyStorage = isTauri();

  const refresh = useCallback(async () => {
    if (!desktopKeyStorage) {
      setHasKey(false);
      return;
    }
    try {
      const status = await getCloudKeyStatus();
      setHasKey(!!status[keyName]);
    } catch {
      setHasKey(false);
    }
  }, [desktopKeyStorage, keyName]);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  return (
    <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
        background: hasKey ? 'var(--color-success)' : 'var(--color-text-tertiary)',
      }} />
      {label}
    </span>
  );
}

const serverInput = (server: McpServerStatus): McpServerInput => ({
  server_id: server.server_id,
  label: server.label,
  transport: server.transport,
  enabled: server.enabled,
  url: server.url || '',
  command: server.command || '',
  args: server.args || [],
  token_env: server.token_env || '',
  include_tools: server.include_tools || [],
  exclude_tools: server.exclude_tools || [],
  tool_policies: server.tool_policies || {},
});

function McpTokenInput({ server, onSaved }: { server: McpServerStatus; onSaved: () => Promise<void> }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const save = async () => {
    if (!value.trim() || !server.token_env) return;
    setError('');
    try {
      await saveCloudKey(server.token_env, value.trim());
      setValue('');
      await onSaved();
    } catch (reason: any) {
      setError(reason?.message || 'Token konnte nicht gespeichert werden.');
    }
  };
  const remove = async () => {
    if (!server.token_env) return;
    setError('');
    try {
      await saveCloudKey(server.token_env, '');
      setValue('');
      await onSaved();
    } catch (reason: any) {
      setError(reason?.message || 'Token konnte nicht entfernt werden.');
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 mt-2">
      <input aria-label={`Token für ${server.label}`} type="password" value={value} onChange={(event) => setValue(event.target.value)}
        placeholder={server.token_configured ? 'Token sicher gespeichert' : 'Bearer-Token (optional)'}
        disabled={!isTauri() || !server.token_env}
        className="px-2 py-1 rounded text-xs"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
      <button type="button" onClick={() => void save()} disabled={!isTauri() || !server.token_env || !value.trim()}
        className="px-2 py-1 rounded text-xs disabled:opacity-40"
        style={{ border: '1px solid var(--color-border)' }}>Token speichern</button>
      {server.token_configured && <button type="button" onClick={() => void remove()}
        className="px-2 py-1 rounded text-xs"
        style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}>Token entfernen</button>}
      {error && <span className="text-xs" style={{ color: 'var(--color-error)' }}>{error}</span>}
    </div>
  );
}

export function McpSettings() {
  const [status, setStatus] = useState<Awaited<ReturnType<typeof fetchMcpStatus>> | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [confirmRemove, setConfirmRemove] = useState('');
  const [draft, setDraft] = useState({
    server_id: '', label: '', transport: 'http' as 'http' | 'stdio', endpoint: '',
    args: '', include: '', exclude: '', token: '',
  });
  const refresh = useCallback(async () => {
    try {
      setStatus(await fetchMcpStatus());
      setError('');
    } catch (reason: any) {
      setStatus(null);
      setError(reason?.message || 'MCP-Status ist nicht verfügbar.');
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const reconnect = async (serverId: string) => {
    setBusy(serverId);
    try {
      setStatus(await reconnectMcpServer(serverId));
      setError('');
    } catch (reason: any) {
      setError(reason?.message || 'Der MCP-Server ist nicht erreichbar.');
      await refresh();
    } finally { setBusy(''); }
  };

  const add = async () => {
    const id = draft.server_id.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9_-]{0,47}$/.test(id) || !draft.endpoint.trim()) {
      setError('Server-ID und Endpunkt sind erforderlich.');
      return;
    }
    const tokenEnv = `MCP_${id.replace(/[^a-z0-9]/g, '_').toUpperCase()}_API_KEY`;
    const input: McpServerInput = {
      server_id: id,
      label: draft.label.trim() || id,
      transport: draft.transport,
      enabled: true,
      url: draft.transport === 'http' ? draft.endpoint.trim() : '',
      command: draft.transport === 'stdio' ? draft.endpoint.trim() : '',
      args: draft.args.split(',').map((item) => item.trim()).filter(Boolean),
      token_env: tokenEnv,
      include_tools: draft.include.split(',').map((item) => item.trim()).filter(Boolean),
      exclude_tools: draft.exclude.split(',').map((item) => item.trim()).filter(Boolean),
      tool_policies: {},
    };
    setBusy(id);
    let serverSaved = false;
    try {
      await saveMcpServer(input);
      serverSaved = true;
      if (draft.token.trim()) await saveCloudKey(tokenEnv, draft.token.trim());
      setDraft({ server_id: '', label: '', transport: 'http', endpoint: '', args: '', include: '', exclude: '', token: '' });
      try {
        setStatus(await reconnectMcpServer(id));
        setError('');
      } catch (reason: any) {
        await refresh();
        setError(`Server gespeichert, aber die Verbindung ist fehlgeschlagen: ${reason?.message || 'nicht erreichbar'}`);
      }
    } catch (reason: any) {
      setError(serverSaved
        ? (reason?.message || 'Server gespeichert, aber der Token konnte nicht geladen werden.')
        : (reason?.message || 'MCP-Server konnte nicht gespeichert werden.'));
    } finally { setBusy(''); }
  };

  const update = async (server: McpServerStatus, patch: Partial<McpServerInput>) => {
    setBusy(server.server_id);
    try {
      const next = { ...serverInput(server), ...patch };
      await saveMcpServer(next);
      if (next.enabled) {
        try {
          setStatus(await reconnectMcpServer(server.server_id));
          setError('');
        } catch (reason: any) {
          await refresh();
          setError(`Einstellung gespeichert, aber die Verbindung ist fehlgeschlagen: ${reason?.message || 'nicht erreichbar'}`);
        }
      } else {
        await refresh();
      }
    } catch (reason: any) {
      setError(reason?.message || 'MCP-Berechtigung konnte nicht gespeichert werden.');
    } finally { setBusy(''); }
  };

  const remove = async (serverId: string) => {
    if (confirmRemove !== serverId) {
      setConfirmRemove(serverId);
      return;
    }
    setBusy(serverId);
    try {
      await removeMcpServer(serverId);
      setConfirmRemove('');
      await refresh();
    } catch (reason: any) {
      setError(reason?.message || 'MCP-Server konnte nicht entfernt werden.');
    } finally { setBusy(''); }
  };

  const setPolicy = async (server: McpServerStatus, tool: McpToolStatus, policy: McpToolStatus['policy']) => {
    await update(server, { tool_policies: { ...server.tool_policies, [tool.name]: policy } });
  };

  return (
    <div className="space-y-3">
      <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        {status ? `${status.connected_servers} verbunden · ${status.discovered_tools} Werkzeuge · ${status.disconnected_servers} getrennt` : 'MCP getrennt'}
      </div>
      {error && <div className="text-xs rounded p-2" style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}>{error}</div>}
      {status?.servers.map((server) => (
        <div key={server.server_id} className="rounded-lg p-3" style={{ border: '1px solid var(--color-border)' }}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium">{server.label}</div>
              <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                {server.server_id} · {server.transport} · {server.connected ? 'verbunden' : server.enabled ? 'getrennt' : 'deaktiviert'}
              </div>
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={() => void update(server, { enabled: !server.enabled })} disabled={!!busy} className="px-2 py-1 rounded text-xs disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
                {server.enabled ? 'Deaktivieren' : 'Aktivieren'}
              </button>
              <button type="button" onClick={() => void reconnect(server.server_id)} disabled={!server.enabled || !!busy} className="px-2 py-1 rounded text-xs disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
                <Plug size={11} className="inline mr-1" />Neu verbinden
              </button>
              <button type="button" onClick={() => void remove(server.server_id)} disabled={!!busy} className="px-2 py-1 rounded text-xs disabled:opacity-40" style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}>{confirmRemove === server.server_id ? 'Entfernen bestätigen' : 'Entfernen'}</button>
            </div>
          </div>
          {server.last_error && <div className="text-xs mt-2" style={{ color: 'var(--color-error)' }}>{server.last_error}</div>}
          {server.last_connected_at && <div className="text-[11px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Letzte Verbindung: {server.last_connected_at}</div>}
          <McpTokenInput server={server} onSaved={() => reconnect(server.server_id)} />
          {server.tools.length > 0 && <div className="mt-3 space-y-1">
            {server.tools.map((tool) => <div key={tool.tool_id} className="flex items-center justify-between gap-2 text-xs">
              <span title={tool.tool_id}>{tool.name}</span>
              <select aria-label={`Berechtigung für ${tool.name}`} value={server.tool_policies[tool.name] || tool.policy} disabled={!!busy} onChange={(event) => void setPolicy(server, tool, event.target.value as McpToolStatus['policy'])}
                className="px-2 py-1 rounded disabled:opacity-40" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                <option value="read">Nur lesen</option><option value="prepare">Vorbereiten + Freigabe</option><option value="write">Schreiben + Freigabe</option><option value="blocked">Blockiert</option>
              </select>
            </div>)}
          </div>}
        </div>
      ))}
      <div className="rounded-lg p-3 space-y-2" style={{ border: '1px dashed var(--color-border)' }}>
        <div className="text-sm font-medium"><Plus size={13} className="inline mr-1" />MCP-Server hinzufügen</div>
        <div className="grid grid-cols-2 gap-2">
          <input aria-label="MCP Server-ID" value={draft.server_id} onChange={(e) => setDraft((v) => ({ ...v, server_id: e.target.value }))} placeholder="server-id" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
          <input aria-label="MCP Anzeigename" value={draft.label} onChange={(e) => setDraft((v) => ({ ...v, label: e.target.value }))} placeholder="Anzeigename" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
          <select aria-label="MCP Transport" value={draft.transport} onChange={(e) => setDraft((v) => ({ ...v, transport: e.target.value as 'http' | 'stdio' }))} className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }}><option value="http">Streamable HTTP</option><option value="stdio">Stdio</option></select>
          <input aria-label="MCP Endpunkt" value={draft.endpoint} onChange={(e) => setDraft((v) => ({ ...v, endpoint: e.target.value }))} placeholder={draft.transport === 'http' ? 'https://…/mcp' : 'C:\\…\\server.exe'} className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
          <input aria-label="MCP Argumente" value={draft.args} onChange={(e) => setDraft((v) => ({ ...v, args: e.target.value }))} placeholder="Argumente, kommagetrennt" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
          <input aria-label="MCP Token" type="password" value={draft.token} onChange={(e) => setDraft((v) => ({ ...v, token: e.target.value }))} disabled={!isTauri()} placeholder="Token (optional, Schlüsselbund)" className="px-2 py-1 rounded text-xs disabled:opacity-50" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
          <input aria-label="MCP Include-Tools" value={draft.include} onChange={(e) => setDraft((v) => ({ ...v, include: e.target.value }))} placeholder="Include-Tools (optional)" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
          <input aria-label="MCP Exclude-Tools" value={draft.exclude} onChange={(e) => setDraft((v) => ({ ...v, exclude: e.target.value }))} placeholder="Exclude-Tools (optional)" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
        </div>
        <button type="button" onClick={() => void add()} disabled={!!busy} className="px-3 py-1.5 rounded text-xs disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>Server speichern</button>
      </div>
      <div className="text-[11px] leading-5" style={{ color: 'var(--color-text-tertiary)' }}>
        <Shield size={11} className="inline mr-1" />Intern integriert: Windows-Desktopadapter. Optional, nicht installiert und nicht verifiziert: GitHub, Google Drive, Gmail, Calendar, Outlook, Teams, Slack und Notion über kompatible MCP-Server. Externe MCPs werden nicht automatisch installiert oder verbunden.
      </div>
    </div>
  );
}

function DesktopAccessSettings() {
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState({ target_id: '', label: '', executable: '', title_contains: '' });
  const refresh = useCallback(async () => {
    try { setStatus(await fetchDesktopStatus()); setError(''); }
    catch (reason: any) { setStatus(null); setError(reason?.message || 'Desktopadapter nicht verfügbar.'); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const save = async () => {
    try {
      await saveDesktopTarget({
        ...draft,
        mode: 'interact',
        capabilities: ['inspect', 'screenshot', 'focus', 'window', 'launch', 'type', 'click', 'hotkey', 'scroll', 'visual_click', 'clipboard'],
      });
      setDraft({ target_id: '', label: '', executable: '', title_contains: '' });
      await refresh();
    } catch (reason: any) { setError(reason?.message || 'Desktopfreigabe konnte nicht gespeichert werden.'); }
  };
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
      <span>
        {status?.mode === 'configured' ? 'Desktopzugriff aktiv' : 'Desktopzugriff inaktiv'} · {status?.current_window || 'kein Zielfenster'}
        {status?.target_monitor ? ` · ${status.target_monitor} · ${status.target_dpi} DPI` : ''}
      </span>
      <button type="button" onClick={async () => { try { await interruptDesktop(); await refresh(); } catch (reason: any) { setError(reason?.message || 'Aktion konnte nicht unterbrochen werden.'); } }} className="px-3 py-1.5 rounded" style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}><Square size={11} className="inline mr-1" />Global Stop</button>
    </div>
    {status?.secure_desktop_blocked && <div className="text-xs" style={{ color: 'var(--color-error)' }}>Windows Secure Desktop kann nicht automatisiert werden ({status.secure_desktop}).</div>}
    {status?.last_action && <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>Letzte Aktion: {status.last_action.action} · {status.last_action.verified ? 'verifiziert' : 'nicht bestätigt'}</div>}
    {status && <div className="text-xs" style={{ color: status.semantic_backend === 'windows_uia' ? 'var(--color-text-secondary)' : 'var(--color-warning)' }}>Semantik: {status.semantic_backend === 'windows_uia' ? 'Windows UI Automation' : status.semantic_backend === 'win32_fallback' ? 'klassischer Win32-Fallback' : 'noch nicht geprüft'}</div>}
    {error && <div className="text-xs" style={{ color: 'var(--color-error)' }}>{error}</div>}
    {status?.targets.map((target) => <div key={target.target_id} className="rounded-lg p-3" style={{ border: '1px solid var(--color-border)' }}>
      <div className="flex justify-between gap-2"><div><div className="text-sm font-medium">{target.label}</div><div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>{target.title_contains} · {target.connected ? 'verbunden' : target.mode}</div></div>
      <div className="flex gap-2"><button type="button" onClick={async () => { try { await connectDesktopTarget(target.target_id); await refresh(); } catch (reason: any) { setError(reason?.message || 'Zielfenster nicht gefunden.'); } }} className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)' }}>Verbinden</button>
      <button type="button" onClick={async () => { await saveDesktopTarget({ target_id: target.target_id, label: target.label, executable: target.executable, title_contains: target.title_contains, mode: 'off', capabilities: target.capabilities }); await refresh(); }} className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)' }}>Abschalten</button></div></div>
      <div className="text-[11px] mt-2" style={{ color: 'var(--color-text-tertiary)' }}>{target.capabilities.join(', ')}</div>
    </div>)}
    <div className="grid grid-cols-2 gap-2">
      <input value={draft.target_id} onChange={(e) => setDraft((v) => ({ ...v, target_id: e.target.value.toLowerCase() }))} placeholder="ziel-id" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
      <input value={draft.label} onChange={(e) => setDraft((v) => ({ ...v, label: e.target.value }))} placeholder="Anwendung" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
      <input value={draft.executable} onChange={(e) => setDraft((v) => ({ ...v, executable: e.target.value }))} placeholder="C:\\…\\app.exe" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
      <input value={draft.title_contains} onChange={(e) => setDraft((v) => ({ ...v, title_contains: e.target.value }))} placeholder="Fenstertitel enthält" className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />
    </div>
    <button type="button" onClick={() => void save()} className="px-3 py-1.5 rounded text-xs" style={{ border: '1px solid var(--color-border)' }}>Dauerhaften Zugriff speichern</button>
    <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>Dauerhafter Desktopzugriff ersetzt keine Level-3-Freigabe. UAC, Anmeldebildschirm, andere Sitzungen und geschützte Passwortfelder bleiben gesperrt.</div>
  </div>;
}

const PERSONAL_KEY = 'openjarvis-personal-preferences-v1';
function PersonalPreferences() {
  const empty = { name: '', address: '', answerLength: '', role: '', applications: '', folders: '', tools: '', voiceId: '', desktopMode: '', approvalLimits: '' };
  const [value, setValue] = useState<typeof empty>(() => { try { return { ...empty, ...JSON.parse(localStorage.getItem(PERSONAL_KEY) || '{}') }; } catch { return empty; } });
  const [saved, setSaved] = useState(false);
  const fields: Array<[keyof typeof empty, string]> = [['name', 'Name'], ['address', 'Bevorzugte Ansprache'], ['answerLength', 'Antwortlänge'], ['role', 'Persönliche/berufliche Rolle'], ['applications', 'Wichtige Anwendungen'], ['folders', 'Häufig genutzte Ordner'], ['tools', 'Bevorzugte Tools und Dienste'], ['voiceId', 'Gewünschte Voice-ID'], ['desktopMode', 'Desktop-Zugriffsmodus'], ['approvalLimits', 'Freigabegrenzen']];
  return <div className="space-y-2"><div className="grid grid-cols-2 gap-2">{fields.map(([key, label]) => <input key={key} value={value[key]} onChange={(e) => setValue((current) => ({ ...current, [key]: e.target.value }))} placeholder={label} className="px-2 py-1 rounded text-xs" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg)' }} />)}</div>
    <button type="button" onClick={() => { localStorage.setItem(PERSONAL_KEY, JSON.stringify(value)); setSaved(true); setTimeout(() => setSaved(false), 1500); }} className="px-3 py-1.5 rounded text-xs" style={{ border: '1px solid var(--color-border)' }}>Freiwillige Angaben speichern</button>{saved && <span className="text-xs ml-2" style={{ color: 'var(--color-success)' }}>Gespeichert</span>}
    <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>Alle Felder dürfen leer bleiben. Diese Angaben werden lokal gespeichert und erteilen allein keine Tool- oder Memory-Freigabe.</div>
  </div>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--color-text)' }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function SettingRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <div>
        <div className="text-sm" style={{ color: 'var(--color-text)' }}>{label}</div>
        {description && (
          <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{description}</div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

const themeOptions: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

export function SettingsPage() {
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const conversations = useAppStore((s) => s.conversations);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [speechBackendAvailable, setSpeechBackendAvailable] = useState<boolean | null>(null);
  const [saved, setSaved] = useState(false);

  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(() => !isAutoUpdateDisabled());
  const [updateCheckState, setUpdateCheckState] = useState<'idle' | 'checking' | 'available' | 'latest'>('idle');

  const handleAutoUpdateToggle = useCallback((enabled: boolean) => {
    setAutoUpdateEnabled(enabled);
    setAutoUpdateDisabled(!enabled);
  }, []);

  const handleCheckNow = useCallback(async () => {
    if (!(window as any).__TAURI_INTERNALS__) return;
    setUpdateCheckState('checking');
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      setUpdateCheckState(update ? 'available' : 'latest');
      setTimeout(() => setUpdateCheckState('idle'), 4000);
    } catch {
      setUpdateCheckState('idle');
    }
  }, []);

  const [memoryStats, setMemoryStats] = useState<{ entries: number; backend: string } | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(() => {
    try { return localStorage.getItem('openjarvis-memory-enabled') !== 'false'; } catch { return true; }
  });
  const [memoryBackend, setMemoryBackend] = useState(() => {
    try { return localStorage.getItem('openjarvis-memory-backend') || 'sqlite'; } catch { return 'sqlite'; }
  });
  const [memoryTopK, setMemoryTopK] = useState(() => {
    try { return parseInt(localStorage.getItem('openjarvis-memory-top-k') || '5'); } catch { return 5; }
  });
  const [memoryMinScore, setMemoryMinScore] = useState(() => {
    try { return parseFloat(localStorage.getItem('openjarvis-memory-min-score') || '0.1'); } catch { return 0.1; }
  });
  const [memoryMaxTokens, setMemoryMaxTokens] = useState(() => {
    try { return parseInt(localStorage.getItem('openjarvis-memory-max-tokens') || '2048'); } catch { return 2048; }
  });

  const [srcKind, setSrcKind] = useState<InferenceSource['kind']>('ollama');
  const [customHost, setCustomHost] = useState('http://localhost:1234/v1');
  const [customModel, setCustomModel] = useState('');
  const [customEngine, setCustomEngine] = useState('lmstudio');
  const [customKey, setCustomKey] = useState('');
  const [srcMsg, setSrcMsg] = useState('');

  useEffect(() => {
    getInferenceSource().then((s) => {
      setSrcKind(s.kind);
      if (s.host) setCustomHost(s.host);
      if (s.model) setCustomModel(s.model);
      if (s.engine) setCustomEngine(s.engine);
    }).catch(() => {});
  }, []);

  const saveSource = useCallback(async () => {
    try {
      if (srcKind === 'custom') {
        await setInferenceSource({ kind: 'custom', host: customHost, model: customModel, engine: customEngine, apiKey: customKey || undefined });
      } else {
        await setInferenceSource({ kind: 'ollama' });
      }
      setSrcMsg('Saved — restart the app to apply.');
    } catch (e: any) {
      setSrcMsg(e?.message ?? 'Failed to save.');
    }
  }, [srcKind, customHost, customModel, customEngine, customKey]);

  useEffect(() => {
    checkHealth().then(setHealthy);
    fetchSpeechHealth()
      .then((h) => setSpeechBackendAvailable(h.available))
      .catch(() => setSpeechBackendAvailable(false));
    getMemoryStats()
      .then(setMemoryStats)
      .catch(() => setMemoryStats(null));
  }, []);

  const showSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const handleExport = () => {
    const data = localStorage.getItem('openjarvis-conversations') || '{}';
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `openjarvis-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const data = JSON.parse(ev.target?.result as string);
          if (data.version === 1) {
            localStorage.setItem('openjarvis-conversations', JSON.stringify(data));
            useAppStore.getState().loadConversations();
            showSaved();
          }
        } catch {}
      };
      reader.readAsText(file);
    };
    input.click();
  };

  const [confirmClear, setConfirmClear] = useState(false);
  const handleClear = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 3000);
      return;
    }
    localStorage.removeItem('openjarvis-conversations');
    useAppStore.getState().loadConversations();
    setConfirmClear(false);
    showSaved();
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-3">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              Settings
            </h1>
            {saved && (
              <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-full" style={{
                background: 'var(--color-accent-subtle)',
                color: 'var(--color-success)',
              }}>
                <Check size={12} /> Saved
              </span>
            )}
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            App preferences — appearance, model defaults, keyboard shortcuts, and data management.
          </p>
        </header>

        <div className="flex flex-col gap-4">
          {/* Appearance */}
          <Section title="Appearance">
            <SettingRow label="Theme" description="Choose how OpenJarvis looks">
              <div className="flex gap-1 p-0.5 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
                {themeOptions.map((opt) => {
                  const isActive = settings.theme === opt.value;
                  return (
                    <button
                      key={opt.value}
                      onClick={() => { updateSettings({ theme: opt.value }); showSaved(); }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: isActive ? 'var(--color-surface)' : 'transparent',
                        color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                        boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                      }}
                    >
                      <opt.icon size={14} />
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </SettingRow>
            <SettingRow label="Font size">
              <select
                value={settings.fontSize}
                onChange={(e) => { updateSettings({ fontSize: e.target.value as any }); showSaved(); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="small">Small</option>
                <option value="default">Default</option>
                <option value="large">Large</option>
              </select>
            </SettingRow>
          </Section>

          {/* Connection */}
          <Section title="Connection">
            <SettingRow label="Server status" description={serverInfo ? `${serverInfo.engine} / ${serverInfo.model}` : 'Not connected'}>
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: healthy === true ? 'var(--color-success)' : healthy === false ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {healthy === true ? 'Connected' : healthy === false ? 'Disconnected' : 'Checking...'}
                </span>
              </div>
            </SettingRow>
            <SettingRow label="API URL" description="Set if backend runs on a different port or host">
              <input
                type="text"
                value={settings.apiUrl}
                onChange={(e) => { updateSettings({ apiUrl: e.target.value }); showSaved(); }}
                placeholder="http://localhost:8000"
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
            <SettingRow label="API key" description="Required only if the server was started with an API key">
              <input
                type="password"
                value={settings.apiKey}
                onChange={(e) => { updateSettings({ apiKey: e.target.value }); showSaved(); }}
                placeholder="OPENJARVIS_API_KEY"
                autoComplete="off"
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
          </Section>

          {/* Inference source */}
          <Section title="Inference source">
            <SettingRow label="Source" description="Where the app runs models. Applies after restart.">
              <select
                value={srcKind}
                onChange={(e) => { setSrcKind(e.target.value as InferenceSource['kind']); setSrcMsg(''); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
              >
                <option value="ollama">Bundled Ollama (default)</option>
                <option value="custom">Custom OpenAI-compatible server</option>
              </select>
            </SettingRow>
            {srcKind === 'custom' && (
              <>
                <SettingRow label="Server URL" description="e.g. LM Studio: http://localhost:1234/v1">
                  <input type="text" value={customHost} onChange={(e) => { setCustomHost(e.target.value); setSrcMsg(''); }} placeholder="http://localhost:1234/v1"
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label="Model" description="Model id served by your endpoint">
                  <input type="text" value={customModel} onChange={(e) => { setCustomModel(e.target.value); setSrcMsg(''); }} placeholder="qwen2.5-7b-instruct"
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label="Server type" description="OpenAI-compatible engine">
                  <select value={customEngine} onChange={(e) => { setCustomEngine(e.target.value); setSrcMsg(''); }}
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                    <option value="lmstudio">LM Studio</option>
                    <option value="vllm">vLLM</option>
                    <option value="sglang">SGLang</option>
                    <option value="llamacpp">llama.cpp</option>
                    <option value="mlx">MLX</option>
                  </select>
                </SettingRow>
                <SettingRow label="API key (optional)" description="Only if your server requires one">
                  <input type="password" value={customKey} onChange={(e) => { setCustomKey(e.target.value); setSrcMsg(''); }} placeholder="leave blank if none"
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
              </>
            )}
            <SettingRow label="" description={srcMsg}>
              <button onClick={saveSource}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{ background: 'var(--color-accent, var(--color-bg-tertiary))', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                Save inference source
              </button>
            </SettingRow>
          </Section>

          {/* Models */}
          <Section title="Models">
            <SettingRow label="Local models (Ollama)" description="Models available for local inference">
              <OllamaModelList />
            </SettingRow>
            <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
              Run <code className="px-1 py-0.5 rounded text-[11px]" style={{ background: 'var(--color-bg-tertiary)' }}>ollama pull &lt;model-name&gt;</code> in your terminal to add more models
            </div>
            <SettingRow label="Cloud providers" description="Green dot means API key is configured">
              <div className="flex flex-wrap gap-3">
                <CloudProviderStatus label="OpenAI" keyName="OPENAI_API_KEY" />
                <CloudProviderStatus label="Anthropic" keyName="ANTHROPIC_API_KEY" />
                <CloudProviderStatus label="Google" keyName="GEMINI_API_KEY" />
                <CloudProviderStatus label="OpenRouter" keyName="OPENROUTER_API_KEY" />
              </div>
            </SettingRow>
          </Section>

          {/* API Keys */}
          <Section title="API Keys">
            <SettingRow label="OpenAI" description="GPT-4, GPT-3.5, etc.">
              <ApiKeyInput keyName="OPENAI_API_KEY" placeholder="sk-..." />
            </SettingRow>
            <SettingRow label="Anthropic" description="Claude models">
              <ApiKeyInput keyName="ANTHROPIC_API_KEY" placeholder="sk-ant-..." />
            </SettingRow>
            <SettingRow label="Google" description="Gemini models">
              <ApiKeyInput keyName="GEMINI_API_KEY" placeholder="AI..." />
            </SettingRow>
            <SettingRow label="OpenRouter" description="Multi-provider routing">
              <ApiKeyInput keyName="OPENROUTER_API_KEY" placeholder="sk-or-..." />
            </SettingRow>
            <SettingRow label="ElevenLabs" description="JARVIS-Sprachausgabe; sicher im Desktop-Schlüsselbund gespeichert">
              <ApiKeyInput keyName="ELEVENLABS_API_KEY" placeholder="sk_..." />
            </SettingRow>
          </Section>

          {/* Tools */}
          <Section title="Tools">
            <SettingRow label="Web Search" description="Tavily key for web search tool">
              <ApiKeyInput keyName="TAVILY_API_KEY" placeholder="tvly-..." />
            </SettingRow>
          </Section>

          <Section title="Windows-Desktopzugriff">
            <DesktopAccessSettings />
          </Section>

          <Section title="MCP-Server und Berechtigungen">
            <McpSettings />
          </Section>

          <Section title="Persönliche Konfiguration (freiwillig)">
            <PersonalPreferences />
          </Section>

          {/* Memory */}
          <Section title="Memory">
            <SettingRow label="Memory status" description={memoryStats ? `${memoryStats.backend} backend — ${memoryStats.entries} entries` : 'Unable to reach memory service'}>
              <div className="flex items-center gap-2">
                <Brain size={14} style={{ color: memoryStats ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {memoryStats ? `${memoryStats.entries} entries` : 'Unavailable'}
                </span>
              </div>
            </SettingRow>
            <SettingRow label="Use memory context" description="Automatically inject relevant memories into conversations">
              <button
                onClick={() => {
                  const next = !memoryEnabled;
                  setMemoryEnabled(next);
                  try { localStorage.setItem('openjarvis-memory-enabled', String(next)); } catch {}
                  showSaved();
                }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: memoryEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: memoryEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Memory backend" description="Which retrieval engine to use">
              <select
                value={memoryBackend}
                onChange={(e) => {
                  setMemoryBackend(e.target.value);
                  try { localStorage.setItem('openjarvis-memory-backend', e.target.value); } catch {}
                  showSaved();
                }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="sqlite">sqlite</option>
                <option value="faiss">faiss</option>
                <option value="bm25">bm25</option>
                <option value="colbert">colbert</option>
                <option value="hybrid">hybrid</option>
              </select>
            </SettingRow>
            <SettingRow label="Results to inject" description={`${memoryTopK}`}>
              <input
                type="range"
                min="1"
                max="20"
                step="1"
                value={memoryTopK}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryTopK(v);
                  try { localStorage.setItem('openjarvis-memory-top-k', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Min relevance score" description={`${memoryMinScore}`}>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={memoryMinScore}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setMemoryMinScore(v);
                  try { localStorage.setItem('openjarvis-memory-min-score', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Max context tokens" description={`${memoryMaxTokens}`}>
              <input
                type="range"
                min="256"
                max="8192"
                step="256"
                value={memoryMaxTokens}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryMaxTokens(v);
                  try { localStorage.setItem('openjarvis-memory-max-tokens', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Model defaults */}
          <Section title="Model Defaults">
            <SettingRow label="Temperature" description={`${settings.temperature}`}>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={settings.temperature}
                onChange={(e) => { updateSettings({ temperature: parseFloat(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Max tokens" description={`${settings.maxTokens}`}>
              <input
                type="range"
                min="256"
                max="32768"
                step="256"
                value={settings.maxTokens}
                onChange={(e) => { updateSettings({ maxTokens: parseInt(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Speech */}
          <Section title="Speech">
            <SettingRow label="Speech-to-Text" description="Enable microphone input for voice dictation">
              <button
                onClick={() => { updateSettings({ speechEnabled: !settings.speechEnabled }); showSaved(); }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.speechEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.speechEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Backend status" description="Requires Whisper, Deepgram, or another speech backend">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: speechBackendAvailable === true ? 'var(--color-success)'
                      : speechBackendAvailable === false ? 'var(--color-text-tertiary)'
                      : 'var(--color-text-tertiary)',
                  }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {speechBackendAvailable === null ? 'Checking...'
                    : speechBackendAvailable ? 'Available'
                    : 'Not configured'}
                </span>
              </div>
            </SettingRow>
            {!speechBackendAvailable && speechBackendAvailable !== null && (
              <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Set up a speech backend to use voice input.
                See the <a href="https://open-jarvis.github.io/OpenJarvis/user-guide/tools/" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)' }}>documentation</a> for details.
              </div>
            )}
          </Section>

          {/* Data */}
          <Section title="Data">
            <SettingRow label="Conversations" description={`${conversations.length} stored locally`}>
              <div className="flex gap-2">
                <button
                  onClick={handleExport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Download size={12} /> Export
                </button>
                <button
                  onClick={handleImport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Upload size={12} /> Import
                </button>
              </div>
            </SettingRow>
            <SettingRow label="Clear all data" description="Permanently delete all conversations">
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                style={{
                  color: confirmClear ? 'white' : 'var(--color-error)',
                  background: confirmClear ? 'var(--color-error)' : 'transparent',
                  border: '1px solid var(--color-error)',
                }}
                onMouseEnter={(e) => { if (!confirmClear) e.currentTarget.style.background = 'rgba(220,38,38,0.1)'; }}
                onMouseLeave={(e) => { if (!confirmClear) e.currentTarget.style.background = 'transparent'; }}
              >
                <Trash2 size={12} /> {confirmClear ? 'Click again to confirm' : 'Clear'}
              </button>
            </SettingRow>
          </Section>

          {/* Updates */}
          <Section title="Updates">
            <SettingRow label="Auto-update" description="Check for new desktop builds automatically every 30 minutes">
              <button
                onClick={() => handleAutoUpdateToggle(!autoUpdateEnabled)}
                className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors"
                style={{ background: autoUpdateEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
              >
                <span
                  className="inline-block h-3.5 w-3.5 rounded-full transition-transform"
                  style={{
                    background: 'white',
                    transform: autoUpdateEnabled ? 'translateX(18px)' : 'translateX(2px)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Check for updates" description="Manually check for a new version right now">
              <button
                onClick={handleCheckNow}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', color: 'var(--color-text)', cursor: 'pointer' }}
                disabled={updateCheckState === 'checking'}
              >
                <RefreshCw size={12} className={updateCheckState === 'checking' ? 'animate-spin' : ''} />
                {updateCheckState === 'checking' && 'Checking...'}
                {updateCheckState === 'available' && 'Update available — see banner above'}
                {updateCheckState === 'latest' && 'Already up to date'}
                {updateCheckState === 'idle' && 'Check now'}
              </button>
            </SettingRow>
          </Section>

          {/* About */}
          <Section title="About">
            <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <p className="mb-2">
                <span className="font-semibold" style={{ color: 'var(--color-text)' }}>OpenJarvis</span> — Programming abstractions for on-device AI.
              </p>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Part of Intelligence Per Watt, a research initiative at Stanford SAIL.
              </p>
              <div className="flex gap-3 mt-3 text-xs">
                <a
                  href="https://scalingintelligence.stanford.edu/blogs/openjarvis/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  Project site
                </a>
                <a
                  href="https://open-jarvis.github.io/OpenJarvis/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  Documentation
                </a>
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
