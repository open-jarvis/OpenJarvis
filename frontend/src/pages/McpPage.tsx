import { useCallback, useEffect, useRef, useState } from 'react';
import { LogIn, LogOut, Lock, Pencil, Plug, Plus, RefreshCw, Trash2 } from 'lucide-react';
import {
  createMcpServer,
  deleteMcpServer,
  emptyMcpForm,
  formFromCatalog,
  formFromServer,
  formToInput,
  getMcpOAuthRedirectUri,
  isToolActive,
  listMcpServers,
  signOutMcpOAuth,
  startMcpOAuth,
  testMcpDraft,
  testMcpServer,
  toggleInput,
  toolToggleInput,
  updateMcpServer,
  type McpCatalogEntry,
  type McpForm,
  type McpServer,
  type McpServerList,
  type McpTestResult,
} from '../lib/mcp-api';
import {
  McpServerForm,
  RestartNotice,
  Toggle,
  inputStyle,
  mutedText,
  serverTarget,
  smallButton,
} from '../components/mcp/McpServerParts';
import { McpCatalog } from '../components/mcp/McpCatalog';

type Editing =
  | { mode: 'catalog' }
  | { mode: 'new'; initial: McpForm; entry?: McpCatalogEntry }
  | { mode: 'edit'; server: McpServer }
  | null;

const errorText = { color: 'var(--color-error)' };

function statusColor(server: McpServer, result?: McpTestResult): string {
  if (!server.enabled) return 'var(--color-text-tertiary)';
  if (!result) return 'var(--color-border)';
  return result.ok ? 'var(--color-success)' : 'var(--color-error)';
}

const OAUTH_LABELS = { signed_out: 'Not signed in', connected: 'Signed in', expired: 'Sign-in expired' } as const;

function statusLabel(server: McpServer, result?: McpTestResult): string {
  if (!server.enabled) return 'Disabled';
  if (server.oauth_status && server.oauth_status !== 'connected') return OAUTH_LABELS[server.oauth_status];
  if (!result) return 'Not tested';
  if (!result.ok) return 'Connection failed';
  const tools = result.tools || [];
  const active = tools.filter((t) => t.active).length;
  return `Connected · ${active}/${tools.length} tools on`;
}

export function McpServerListItem({
  server,
  result,
  selected,
  onSelect,
}: {
  server: McpServer;
  result?: McpTestResult;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      className="w-full text-left px-3 py-2 rounded-lg cursor-pointer flex items-start gap-2"
      style={{ background: selected ? 'var(--color-bg-tertiary)' : 'transparent' }}
    >
      <span className="mt-1.5 w-2 h-2 rounded-full shrink-0" style={{ background: statusColor(server, result) }} />
      <span className="min-w-0">
        <span className="text-sm flex items-center gap-1.5 truncate" style={{ color: 'var(--color-text)' }}>
          {server.name}
          {server.read_only && <Lock size={10} style={mutedText} aria-label="Defined in config.toml" />}
        </span>
        <span className="block text-[11px] truncate" style={mutedText}>
          {statusLabel(server, result)}
        </span>
      </span>
    </button>
  );
}

export function McpServerDetail({
  server,
  result,
  busy,
  onTest,
  onEdit,
  onDelete,
  onToggle,
  onToggleTool,
  onSignIn,
  onSignOut,
}: {
  server: McpServer;
  result?: McpTestResult;
  busy: boolean;
  onTest: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
  onToggleTool: (tool: string, active: boolean) => void;
  onSignIn?: () => void;
  onSignOut?: () => void;
}) {
  const tools = result?.ok ? result.tools || [] : [];
  return (
    <div>
      <div className="flex items-start justify-between gap-3 pb-4" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
        <div className="min-w-0">
          <h2 className="text-base font-semibold flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
            {server.name}
            <span className="text-[10px] uppercase px-1 rounded font-normal" style={{ ...mutedText, border: '1px solid var(--color-border)' }}>
              {server.transport}
            </span>
          </h2>
          <div className="text-xs mt-1 font-mono break-all" style={mutedText}>
            {serverTarget(server)}
            {server.has_token && ' · token saved'}
            {server.env_set.length > 0 && ` · ${server.env_set.join(', ')} saved`}
          </div>
          {server.read_only && (
            <div className="text-[11px] mt-1 flex items-center gap-1" style={mutedText}>
              <Lock size={10} /> Defined in config.toml. Edit that file to change it.
            </div>
          )}
          {server.oauth_status && (
            <div className="text-xs mt-2 flex items-center gap-2">
              <span
                style={{ color: server.oauth_status === 'connected' ? 'var(--color-success)' : 'var(--color-text-secondary)' }}
              >
                {OAUTH_LABELS[server.oauth_status]}
              </span>
              {server.oauth_status === 'connected' ? (
                <button type="button" onClick={onSignOut} disabled={busy} className={smallButton} style={inputStyle}>
                  <LogOut size={11} /> Sign out
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onSignIn}
                  disabled={busy}
                  className={smallButton}
                  style={{ background: 'var(--color-accent)', color: 'white', border: '1px solid var(--color-accent)' }}
                >
                  <LogIn size={11} /> {server.oauth_status === 'expired' ? 'Sign in again' : 'Sign in'}
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button type="button" onClick={onTest} disabled={busy} className={smallButton} style={inputStyle}>
            <RefreshCw size={11} className={busy ? 'animate-spin' : undefined} /> Test
          </button>
          {!server.read_only && (
            <>
              <button type="button" onClick={onEdit} className={smallButton} style={inputStyle}>
                <Pencil size={11} /> Edit
              </button>
              <button
                type="button"
                onClick={onDelete}
                disabled={busy}
                className={smallButton}
                style={{ ...errorText, border: '1px solid var(--color-error)' }}
              >
                <Trash2 size={11} /> Delete
              </button>
              <Toggle on={server.enabled} onClick={onToggle} label={`Enable ${server.name}`} disabled={busy} />
            </>
          )}
        </div>
      </div>

      <div className="pt-4">
        <div className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
          Tools{result?.ok ? ` (${tools.length})` : ''}
        </div>
        {!result && (
          <div className="text-xs" style={mutedText}>
            {busy
              ? 'Connecting…'
              : server.oauth_status && server.oauth_status !== 'connected'
                ? 'Sign in to list its tools.'
                : 'Test the server to list its tools.'}
          </div>
        )}
        {result && !result.ok && <div className="text-xs break-words" style={errorText}>{result.error}</div>}
        {result?.ok && tools.length === 0 && <div className="text-xs" style={mutedText}>This server has no tools.</div>}
        {tools.length > 0 && (
          <ul>
            {tools.map((tool) => (
              <li
                key={tool.name}
                className="flex items-center justify-between gap-3 py-2"
                style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
              >
                <div className="min-w-0">
                  <div className="text-xs font-mono" style={tool.active ? { color: 'var(--color-text)' } : mutedText}>
                    {tool.name}
                  </div>
                  {tool.description && (
                    <div className="text-[11px] mt-0.5" style={mutedText}>
                      {tool.description}
                    </div>
                  )}
                </div>
                <Toggle
                  on={tool.active}
                  onClick={() => onToggleTool(tool.name, !tool.active)}
                  label={`Use tool ${tool.name}`}
                  disabled={busy || server.read_only}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function McpPage() {
  const [data, setData] = useState<McpServerList | null>(null);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, McpTestResult>>({});
  const [redirectUri, setRedirectUri] = useState('');

  const refresh = useCallback(async () => {
    try {
      const list = await listMcpServers();
      setData(list);
      setLoadError('');
      return list;
    } catch (e: any) {
      setLoadError(e?.message || 'Could not load MCP servers');
      return null;
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    getMcpOAuthRedirectUri()
      .then((r) => setRedirectUri(r.redirect_uri))
      .catch(() => setRedirectUri(''));
  }, []);

  const all = data ? [...data.servers, ...data.config_servers] : [];
  const selected = all.find((s) => s.id === selectedId) || (editing ? null : all[0]) || null;

  const withBusy = async (id: string, fn: () => Promise<void>) => {
    setBusyId(id);
    setActionError('');
    try {
      await fn();
    } catch (e: any) {
      setActionError(e?.message || 'Request failed');
    } finally {
      setBusyId(null);
    }
  };

  const test = useCallback(
    (server: McpServer) =>
      withBusy(server.id, async () => {
        const result = await testMcpServer(server.id);
        setResults((r) => ({ ...r, [server.id]: result }));
      }),
    [],
  );

  // List tools when a server is first opened.
  const selectedKey = selected?.id;
  useEffect(() => {
    const signedOut = selected?.oauth_status && selected.oauth_status !== 'connected';
    if (selected && selected.enabled && !signedOut && !results[selected.id] && busyId === null) void test(selected);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey]);

  // The sign-in window tells us when it is done; re-read and re-test then.
  const signingIn = useRef<{ id: string; popup: Window } | null>(null);
  const finishSignIn = useCallback(async () => {
    const current = signingIn.current;
    if (!current) return;
    signingIn.current = null;
    const list = await refresh();
    const server = list?.servers.find((s) => s.id === current.id);
    setResults(({ [current.id]: _stale, ...rest }) => rest);
    if (server?.oauth_status === 'connected') void test(server);
  }, [refresh, test]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === 'openjarvis-mcp-oauth') void finishSignIn();
    };
    window.addEventListener('message', onMessage);
    const timer = window.setInterval(() => {
      if (signingIn.current?.popup.closed) void finishSignIn();
    }, 1000);
    return () => {
      window.removeEventListener('message', onMessage);
      window.clearInterval(timer);
    };
  }, [finishSignIn]);

  const signIn = (server: McpServer) => {
    // Open the window during the click so it is not blocked as a popup.
    const popup = window.open('', 'openjarvis-mcp-oauth', 'width=520,height=700');
    void withBusy(server.id, async () => {
      try {
        const { authorization_url } = await startMcpOAuth(server.id);
        if (!popup) {
          window.location.assign(authorization_url);
          return;
        }
        popup.location.href = authorization_url;
        signingIn.current = { id: server.id, popup };
      } catch (e) {
        popup?.close();
        throw e;
      }
    });
  };

  const toggleTool = (server: McpServer, tool: string, active: boolean) =>
    withBusy(server.id, async () => {
      const { server: saved } = await updateMcpServer(server.id, toolToggleInput(server, tool, active));
      setResults((r) => {
        const current = r[server.id];
        if (!current?.tools) return r;
        const tools = current.tools.map((t) => ({ ...t, active: isToolActive(saved, t.name) }));
        return { ...r, [server.id]: { ...current, tools } };
      });
      await refresh();
    });

  const editingServer = editing?.mode === 'edit' ? editing.server : null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden px-6 py-10">
      <div className="max-w-5xl mx-auto w-full flex flex-col flex-1 overflow-hidden">
        <header className="mb-6 shrink-0">
          <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
            MCP servers
          </h1>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            Connect OpenJarvis to MCP servers. Their tools become available to agents; turn off any tool you do not want used.
          </p>
        </header>

        {data && !data.enabled && (
          <div className="text-xs mb-3" style={errorText}>
            MCP is turned off in config.toml (<span className="font-mono">[tools.mcp] enabled = false</span>). Servers below are not loaded.
          </div>
        )}
        {data?.restart_required && <RestartNotice />}
        {loadError && <div className="text-xs mb-3" style={errorText}>{loadError}</div>}
        {data?.config_error && <div className="text-xs mb-3" style={errorText}>{data.config_error}</div>}
        {actionError && <div className="text-xs mb-3 break-words" style={errorText}>{actionError}</div>}

        <div className="flex flex-col md:flex-row gap-4 flex-1 overflow-hidden min-h-0">
          <aside
            className="md:w-64 shrink-0 rounded-lg p-2 overflow-y-auto"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <button
              type="button"
              onClick={() => {
                setEditing({ mode: 'catalog' });
                setSelectedId(null);
              }}
              className={`${smallButton} w-full justify-center mb-2 py-1.5`}
              style={inputStyle}
            >
              <Plus size={11} /> Add server
            </button>
            {data && all.length === 0 && (
              <div className="text-xs px-3 py-3 flex items-center gap-2" style={mutedText}>
                <Plug size={14} /> No MCP servers yet.
              </div>
            )}
            {all.map((server) => (
              <McpServerListItem
                key={server.id}
                server={server}
                result={results[server.id]}
                selected={!editing && selected?.id === server.id}
                onSelect={() => {
                  setEditing(null);
                  setSelectedId(server.id);
                }}
              />
            ))}
          </aside>

          <section
            className="flex-1 rounded-lg p-5 overflow-y-auto min-w-0"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            {editing?.mode === 'catalog' ? (
              <McpCatalog
                onPick={(entry) => setEditing({ mode: 'new', initial: formFromCatalog(entry), entry })}
                onCustom={() => setEditing({ mode: 'new', initial: emptyMcpForm })}
              />
            ) : editing ? (
              <>
                <h2 className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
                  {editingServer ? `Edit ${editingServer.name}` : editing.mode === 'new' && editing.entry ? `Add ${editing.entry.name}` : 'Add MCP server'}
                </h2>
                {editing.mode === 'new' && editing.entry && (
                  <p className="text-xs mt-1" style={mutedText}>
                    {editing.entry.auth_note}{' '}
                    <a href={editing.entry.source} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)' }}>
                      Docs
                    </a>
                  </p>
                )}
                <McpServerForm
                  key={editingServer?.id || (editing.mode === 'new' && editing.entry?.id) || 'new'}
                  initial={editingServer ? formFromServer(editingServer) : editing.mode === 'new' ? editing.initial : emptyMcpForm}
                  editing={!!editingServer}
                  savedToken={!!editingServer?.has_token}
                  savedEnv={editingServer?.env_set}
                  savedClientSecret={!!editingServer?.has_client_secret}
                  oauthSetup={editing.mode === 'new' ? editing.entry?.oauth_setup : undefined}
                  redirectUri={redirectUri}
                  onCancel={() => setEditing(editing.mode === 'new' ? { mode: 'catalog' } : null)}
                  onTest={(form) =>
                    testMcpDraft({ ...formToInput(form, { editing: !!editingServer }), id: editingServer?.id })
                  }
                  onSave={async (form) => {
                    const input = formToInput(form, { editing: !!editingServer });
                    const { server } = editingServer
                      ? await updateMcpServer(editingServer.id, input)
                      : await createMcpServer(input);
                    setResults(({ [server.id]: _stale, ...rest }) => rest);
                    setEditing(null);
                    setSelectedId(server.id);
                    await refresh();
                  }}
                />
              </>
            ) : selected ? (
              <McpServerDetail
                server={selected}
                result={results[selected.id]}
                busy={busyId === selected.id}
                onTest={() => void test(selected)}
                onEdit={() => setEditing({ mode: 'edit', server: selected })}
                onToggle={() =>
                  void withBusy(selected.id, async () => {
                    await updateMcpServer(selected.id, toggleInput(selected, !selected.enabled));
                    await refresh();
                  })
                }
                onDelete={() => {
                  if (!window.confirm(`Delete MCP server "${selected.name}"?`)) return;
                  void withBusy(selected.id, async () => {
                    await deleteMcpServer(selected.id);
                    setSelectedId(null);
                    await refresh();
                  });
                }}
                onToggleTool={(tool, active) => void toggleTool(selected, tool, active)}
                onSignIn={() => signIn(selected)}
                onSignOut={() =>
                  void withBusy(selected.id, async () => {
                    await signOutMcpOAuth(selected.id);
                    setResults(({ [selected.id]: _stale, ...rest }) => rest);
                    await refresh();
                  })
                }
              />
            ) : (
              data && (
                <McpCatalog
                  onPick={(entry) => setEditing({ mode: 'new', initial: formFromCatalog(entry), entry })}
                  onCustom={() => setEditing({ mode: 'new', initial: emptyMcpForm })}
                />
              )
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
