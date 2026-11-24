import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import {
  ArrowLeft,
  FileText,
  Folder,
  FolderPlus,
  Loader2,
  Play,
  Plus,
  Save,
  ShieldCheck,
  Terminal,
  X,
} from 'lucide-react';
import { isTauri } from '../lib/api';
import {
  getLocalAccessSettings,
  launchAllowedApp,
  listLocalFiles,
  readLocalFile,
  runAllowedCommand,
  setLocalAccessSettings,
  writeLocalFile,
  type LocalAccessSettings,
  type LocalCommandResult,
  type LocalFileEntry,
} from '../lib/local-access';

const SAFE_COMMANDS = [
  'git status --short',
  'git diff --stat',
  'git diff --name-only',
  'git log --oneline -10',
  'git branch --show-current',
];

const EMPTY_SETTINGS: LocalAccessSettings = {
  enabled: false,
  allowedDirs: [],
  allowedApps: [],
  allowedCommands: [],
};

type Confirmation =
  | { kind: 'overwrite'; path: string }
  | { kind: 'launch'; app: string }
  | { kind: 'command'; command: string };

function parentPath(path: string): string | null {
  const normalized = path.replace(/[\\/]+$/, '');
  const separator = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'));
  if (separator < 0) return null;
  const parent = normalized.slice(0, separator);
  if (/^[a-z]:$/i.test(parent)) return `${parent}\\`;
  if (!parent && separator === 0) return path[0] ?? null;
  return parent || null;
}

function containsPath(root: string, path: string): boolean {
  const normalizedRoot = root.replace(/[\\/]+$/, '');
  const normalizedPath = path.replace(/[\\/]+$/, '');
  const isWindowsPath = root.includes('\\') || path.includes('\\')
    || /^[a-z]:/i.test(root) || /^[a-z]:/i.test(path);
  const separator = isWindowsPath ? '\\' : '/';
  const comparableRoot = isWindowsPath ? normalizedRoot.toLowerCase() : normalizedRoot;
  const comparablePath = isWindowsPath ? normalizedPath.toLowerCase() : normalizedPath;
  return comparablePath === comparableRoot
    || comparablePath.startsWith(`${comparableRoot}${separator}`);
}

function SettingsList({
  title,
  values,
  onRemove,
  children,
}: {
  title: string;
  values: string[];
  onRemove: (value: string) => void;
  children?: ReactNode;
}) {
  return (
    <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text)' }}>{title}</h3>
      <div className="space-y-2">
        {values.map((value) => (
          <div key={value} className="flex items-center gap-2 min-w-0 text-xs">
            <span className="flex-1 truncate font-mono" style={{ color: 'var(--color-text-secondary)' }}>{value}</span>
            <button type="button" onClick={() => onRemove(value)} aria-label={`Remove ${value}`} className="p-1 rounded cursor-pointer" style={{ color: 'var(--color-error)' }}>
              <X size={14} />
            </button>
          </div>
        ))}
        {values.length === 0 && <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>None configured</p>}
      </div>
      {children}
    </section>
  );
}

export function LocalAccessPage() {
  const navigate = useNavigate();
  const [settings, setSettings] = useState<LocalAccessSettings>(EMPTY_SETTINGS);
  const [savedSettings, setSavedSettings] = useState<LocalAccessSettings>(EMPTY_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [currentDirectory, setCurrentDirectory] = useState('');
  const [entries, setEntries] = useState<LocalFileEntry[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [savedContent, setSavedContent] = useState('');
  const [newFileName, setNewFileName] = useState('');
  const [appInput, setAppInput] = useState('');
  const [commandInput, setCommandInput] = useState(SAFE_COMMANDS[0]);
  const [commandResult, setCommandResult] = useState<LocalCommandResult | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const isDesktop = isTauri();
  const dirty = useMemo(
    () => JSON.stringify(settings) !== JSON.stringify(savedSettings),
    [settings, savedSettings],
  );
  const active = isDesktop && savedSettings.enabled && !dirty;
  const currentRoot = savedSettings.allowedDirs.find((root) => containsPath(root, currentDirectory)) ?? '';
  const canGoParent = !!currentRoot
    && !!parentPath(currentDirectory)
    && containsPath(currentRoot, parentPath(currentDirectory)!);
  const hasUnsavedDocument = selectedFile
    ? fileContent !== savedContent
    : !!newFileName.trim() || fileContent !== '';

  const refreshSettings = useCallback(async () => {
    if (!isDesktop) {
      setLoading(false);
      return;
    }
    try {
      const current = await getLocalAccessSettings();
      setSettings(current);
      setSavedSettings(current);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [isDesktop]);

  useEffect(() => {
    void refreshSettings();
  }, [refreshSettings]);

  const refreshFiles = useCallback(async (directory: string) => {
    if (!active || !directory) {
      setEntries([]);
      return;
    }
    setFilesLoading(true);
    setError('');
    try {
      setEntries(await listLocalFiles(directory));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setEntries([]);
    } finally {
      setFilesLoading(false);
    }
  }, [active]);

  useEffect(() => {
    if (!currentDirectory && savedSettings.allowedDirs.length > 0) {
      setCurrentDirectory(savedSettings.allowedDirs[0]);
    }
  }, [currentDirectory, savedSettings.allowedDirs]);

  useEffect(() => {
    if (active && currentDirectory) void refreshFiles(currentDirectory);
  }, [active, currentDirectory, refreshFiles]);

  const saveSettings = async () => {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const saved = await setLocalAccessSettings(settings);
      setSettings(saved);
      setSavedSettings(saved);
      setNotice('Local access settings saved.');
      if (saved.allowedDirs.length > 0 && !saved.allowedDirs.some((root) => containsPath(root, currentDirectory))) {
        setCurrentDirectory(saved.allowedDirs[0]);
        setSelectedFile('');
        setFileContent('');
        setSavedContent('');
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };

  const addFolder = async () => {
    setError('');
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const selected = await open({ directory: true, multiple: false });
      if (typeof selected === 'string' && !settings.allowedDirs.includes(selected)) {
        setSettings((current) => ({ ...current, allowedDirs: [...current.allowedDirs, selected] }));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const openFile = async (entry: LocalFileEntry) => {
    if (hasUnsavedDocument) {
      setError('Save the current document before opening another file or folder.');
      return;
    }
    if (entry.isDir) {
      setSelectedFile('');
      setFileContent('');
      setSavedContent('');
      setCurrentDirectory(entry.path);
      return;
    }
    setError('');
    try {
      const content = await readLocalFile(entry.path);
      setFileContent(content);
      setSavedContent(content);
      setSelectedFile(entry.path);
      setNewFileName('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const saveDocument = async (confirmOverwrite: boolean) => {
    const target = selectedFile || (newFileName.trim()
      ? `${currentDirectory}${currentDirectory.match(/[\\/]$/) ? '' : currentDirectory.includes('\\') ? '\\' : '/'}${newFileName.trim()}`
      : '');
    if (!target) {
      setError('Choose an existing document or enter a new filename.');
      return;
    }
    setActionBusy(true);
    setError('');
    setNotice('');
    try {
      await writeLocalFile(target, fileContent, confirmOverwrite);
      setSelectedFile(target);
      setSavedContent(fileContent);
      setNewFileName('');
      setNotice('Document saved.');
      setConfirmation(null);
      await refreshFiles(currentDirectory);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setActionBusy(false);
    }
  };

  const performConfirmedAction = async () => {
    if (!confirmation) return;
    setActionBusy(true);
    setError('');
    setNotice('');
    setCommandResult(null);
    try {
      if (confirmation.kind === 'overwrite') {
        await saveDocument(true);
      } else if (confirmation.kind === 'launch') {
        await launchAllowedApp(confirmation.app, true);
        setNotice(`Launched ${confirmation.app}.`);
        setConfirmation(null);
      } else {
        setCommandResult(await runAllowedCommand(confirmation.command, true));
        setConfirmation(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setActionBusy(false);
    }
  };

  const launch = async (app: string) => {
    setConfirmation({ kind: 'launch', app });
  };

  const runCommand = () => {
    if (!savedSettings.allowedCommands.includes(commandInput)) {
      setError('Save this command to the allowlist before running it.');
      return;
    }
    setConfirmation({ kind: 'command', command: commandInput });
  };

  const askAboutDocument = () => {
    if (!selectedFile) return;
    sessionStorage.setItem('openjarvis-local-document-draft', JSON.stringify({
      path: selectedFile,
      content: fileContent,
    }));
    navigate('/');
  };

  if (!isDesktop) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="max-w-md text-center">
          <ShieldCheck size={32} className="mx-auto mb-3" style={{ color: 'var(--color-accent)' }} />
          <h1 className="text-lg font-semibold mb-2" style={{ color: 'var(--color-text)' }}>Local Access</h1>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>File access and application controls are only available in the OpenJarvis desktop app.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return <div className="flex-1 flex items-center justify-center"><Loader2 className="animate-spin" /></div>;
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6">
      <div className="max-w-6xl mx-auto space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>Local Access</h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>Manage the folders, apps, and safe commands OpenJarvis can access.</p>
          </div>
          <div className="flex items-center gap-2 text-xs px-3 py-2 rounded-full" style={{ background: active ? 'color-mix(in srgb, var(--color-success) 12%, transparent)' : 'var(--color-bg-secondary)', color: active ? 'var(--color-success)' : 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>
            <span className="w-2 h-2 rounded-full" style={{ background: active ? 'var(--color-success)' : 'var(--color-text-tertiary)' }} />
            {active ? 'Enabled' : 'Disabled'}
          </div>
        </header>

        <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <ShieldCheck size={18} className="mt-0.5" style={{ color: 'var(--color-accent)' }} />
              <div>
                <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Computer access</h2>
                <p className="text-xs mt-1 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>Off by default. Access is limited to the folders and exact app/command allowlists below. Commands never run through a shell; file deletion and script interpreters are not supported.</p>
              </div>
            </div>
            <label className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--color-text)' }}>
              <input type="checkbox" checked={settings.enabled} onChange={(event) => setSettings((current) => ({ ...current, enabled: event.target.checked }))} />
              Enable local access
            </label>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => void saveSettings()} disabled={!dirty || saving} className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium disabled:opacity-40 cursor-pointer" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Save settings
            </button>
            {dirty && <span className="text-xs" style={{ color: 'var(--color-warning)' }}>Unsaved changes — access actions are paused until saved.</span>}
            {notice && <span className="text-xs" role="status" style={{ color: 'var(--color-success)' }}>{notice}</span>}
          </div>
        </section>

        {error && <div role="alert" className="rounded-lg px-3 py-2 text-sm" style={{ color: 'var(--color-error)', background: 'color-mix(in srgb, var(--color-error) 10%, transparent)' }}>{error}</div>}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <SettingsList title="Allowed folders" values={settings.allowedDirs} onRemove={(path) => setSettings((current) => ({ ...current, allowedDirs: current.allowedDirs.filter((item) => item !== path) }))}>
            <button type="button" onClick={() => void addFolder()} className="mt-3 flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--color-accent)' }}><FolderPlus size={14} /> Add folder…</button>
          </SettingsList>
          <SettingsList title="Allowed applications" values={settings.allowedApps} onRemove={(app) => setSettings((current) => ({ ...current, allowedApps: current.allowedApps.filter((item) => item !== app) }))}>
            <form className="mt-3 flex gap-2" onSubmit={(event) => { event.preventDefault(); const app = appInput.trim(); if (app && !settings.allowedApps.includes(app)) setSettings((current) => ({ ...current, allowedApps: [...current.allowedApps, app] })); setAppInput(''); }}>
              <input value={appInput} onChange={(event) => setAppInput(event.target.value)} placeholder="Application name or executable path" className="min-w-0 flex-1 px-2 py-1.5 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
              <button type="submit" className="p-2 rounded cursor-pointer" aria-label="Add application" style={{ color: 'var(--color-accent)' }}><Plus size={15} /></button>
            </form>
          </SettingsList>
        </div>

        <SettingsList title="Safe shell command allowlist" values={settings.allowedCommands} onRemove={(command) => setSettings((current) => ({ ...current, allowedCommands: current.allowedCommands.filter((item) => item !== command) }))}>
          <p className="text-[11px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Only these fixed, read-only Git commands are supported. Each run still requires confirmation.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <select value={commandInput} onChange={(event) => setCommandInput(event.target.value)} className="min-w-0 flex-1 px-2 py-1.5 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
              {SAFE_COMMANDS.map((command) => <option key={command} value={command}>{command}</option>)}
            </select>
            <button type="button" onClick={() => setSettings((current) => current.allowedCommands.includes(commandInput) ? current : ({ ...current, allowedCommands: [...current.allowedCommands, commandInput] }))} className="flex items-center gap-1 px-2 py-1.5 rounded text-xs cursor-pointer" style={{ color: 'var(--color-accent)', border: '1px solid var(--color-border)' }}><Plus size={13} /> Allow</button>
            <button type="button" disabled={!active || !savedSettings.allowedCommands.includes(commandInput)} onClick={runCommand} className="flex items-center gap-1 px-2 py-1.5 rounded text-xs disabled:opacity-40 cursor-pointer" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}><Terminal size={13} /> Run…</button>
          </div>
          {commandResult && (
            <pre className="mt-3 max-h-48 overflow-auto rounded-lg p-3 text-xs whitespace-pre-wrap" style={{ background: 'var(--color-bg)', color: commandResult.success ? 'var(--color-text-secondary)' : 'var(--color-error)' }}>
              Exit code: {commandResult.returnCode ?? 'unknown'}<br />
              {commandResult.stdout}{commandResult.stderr ? `\n${commandResult.stderr}` : ''}{!commandResult.stdout && !commandResult.stderr ? '(no output)' : ''}
            </pre>
          )}
        </SettingsList>

        <section className="rounded-xl overflow-hidden" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <div className="flex flex-wrap items-center gap-2 px-4 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
            <FileText size={16} style={{ color: 'var(--color-accent)' }} />
            <h2 className="text-sm font-semibold flex-1" style={{ color: 'var(--color-text)' }}>Documents</h2>
            <button type="button" disabled={!active || !currentDirectory} onClick={() => { if (hasUnsavedDocument) { setError('Save the current document before starting another.'); return; } setSelectedFile(''); setFileContent(''); setSavedContent(''); setNewFileName(''); }} className="flex items-center gap-1 px-2 py-1 rounded text-xs disabled:opacity-40 cursor-pointer" style={{ color: 'var(--color-accent)' }}><Plus size={13} /> New document</button>
          </div>
          {!active ? (
            <p className="px-4 py-6 text-sm" style={{ color: 'var(--color-text-secondary)' }}>Save settings with local access enabled to browse its allowed folders.</p>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(180px,0.8fr)_minmax(0,1.4fr)] min-h-[360px]">
              <div className="border-b lg:border-b-0 lg:border-r p-3" style={{ borderColor: 'var(--color-border)' }}>
                <div className="flex items-center gap-2 mb-2">
                  {canGoParent && (
                    <button type="button" onClick={() => { if (hasUnsavedDocument) { setError('Save the current document before changing folders.'); return; } setCurrentDirectory(parentPath(currentDirectory)!); }} aria-label="Parent folder" className="p-1 rounded cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}><ArrowLeft size={14} /></button>
                  )}
                  <select value={currentRoot} onChange={(event) => { if (hasUnsavedDocument) { setError('Save the current document before changing folders.'); return; } setCurrentDirectory(event.target.value); setSelectedFile(''); setFileContent(''); setSavedContent(''); }} className="min-w-0 flex-1 px-2 py-1.5 rounded text-[11px]" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    {savedSettings.allowedDirs.map((path) => <option key={path} value={path}>{path}</option>)}
                  </select>
                  <button type="button" onClick={() => void refreshFiles(currentDirectory)} title="Refresh folder" className="p-1 rounded cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>↻</button>
                </div>
                <p className="truncate px-1 pb-2 text-[10px] font-mono" title={currentDirectory} style={{ color: 'var(--color-text-tertiary)' }}>{currentDirectory}</p>
                {filesLoading ? <div className="p-4 flex justify-center"><Loader2 size={16} className="animate-spin" /></div> : (
                  <div className="space-y-0.5">
                    {entries.map((entry) => (
                      <button key={entry.path} type="button" onClick={() => void openFile(entry)} className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-xs cursor-pointer" style={{ background: selectedFile === entry.path ? 'var(--color-accent-subtle)' : 'transparent', color: 'var(--color-text-secondary)' }}>
                        {entry.isDir ? <Folder size={14} /> : <FileText size={14} />}
                        <span className="truncate">{entry.name}</span>
                      </button>
                    ))}
                    {entries.length === 0 && <p className="px-2 py-3 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No supported documents in this folder.</p>}
                  </div>
                )}
              </div>
              <div className="flex flex-col p-3 min-h-[300px]">
                {selectedFile ? <p className="text-[11px] font-mono truncate mb-2" style={{ color: 'var(--color-text-tertiary)' }}>{selectedFile}</p> : (
                  <input value={newFileName} onChange={(event) => setNewFileName(event.target.value)} placeholder="New filename (for example notes.md)" className="px-2 py-1.5 rounded text-xs mb-2" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                )}
                <textarea value={fileContent} onChange={(event) => setFileContent(event.target.value)} placeholder="Open a document or create one…" disabled={!active} className="flex-1 min-h-[220px] resize-y p-3 rounded-lg text-xs font-mono outline-none" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                <div className="flex items-center justify-between gap-2 mt-2">
                  <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>Markdown, text, CSV, and JSON · 1 MiB maximum</span>
                  <div className="flex gap-2">
                    {selectedFile && <button type="button" onClick={askAboutDocument} className="px-2 py-1.5 rounded text-xs cursor-pointer" title="Prefill a chat with this document; review it before sending" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>Ask Jarvis</button>}
                    <button type="button" disabled={!active || (!selectedFile && !newFileName.trim()) || actionBusy} onClick={() => selectedFile ? setConfirmation({ kind: 'overwrite', path: selectedFile }) : void saveDocument(false)} className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs disabled:opacity-40 cursor-pointer" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
                      {actionBusy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                      Save
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>

        <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text)' }}>Launch an allowed application</h2>
          <div className="flex flex-wrap gap-2">
            {savedSettings.allowedApps.map((app) => (
              <button key={app} type="button" disabled={!active} onClick={() => void launch(app)} className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs disabled:opacity-40 cursor-pointer" style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}><Play size={13} />{app}</button>
            ))}
            {savedSettings.allowedApps.length === 0 && <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Add apps to the allowlist above.</p>}
          </div>
        </section>
      </div>

      {confirmation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.62)' }}>
          <div role="dialog" aria-modal="true" aria-labelledby="local-access-confirm-title" className="w-full max-w-lg rounded-xl p-5 shadow-2xl" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
            <h2 id="local-access-confirm-title" className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>Confirm local action</h2>
            <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              {confirmation.kind === 'overwrite' && <>Overwrite this document?</>}
              {confirmation.kind === 'launch' && <>Launch this application?</>}
              {confirmation.kind === 'command' && <>Run this exact allowlisted command?</>}
            </p>
            <pre className="my-3 max-h-40 overflow-auto rounded-lg p-3 text-xs whitespace-pre-wrap break-all" style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>
              {confirmation.kind === 'overwrite' ? confirmation.path : confirmation.kind === 'launch' ? confirmation.app : confirmation.command}
            </pre>
            <p className="text-xs" style={{ color: 'var(--color-warning)' }}>This action runs on your computer. Continue only if you recognize it.</p>
            <div className="flex justify-end gap-2 mt-4">
              <button type="button" onClick={() => setConfirmation(null)} disabled={actionBusy} className="px-3 py-2 rounded-lg text-xs cursor-pointer" style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>Cancel</button>
              <button type="button" onClick={() => void performConfirmedAction()} disabled={actionBusy} className="px-3 py-2 rounded-lg text-xs font-medium disabled:opacity-50 cursor-pointer" style={{ background: 'var(--color-error)', color: '#fff' }}>{actionBusy ? 'Working…' : 'Confirm'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
