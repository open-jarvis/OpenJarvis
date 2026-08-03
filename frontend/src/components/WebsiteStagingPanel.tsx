import { useState } from 'react';
import { AlertTriangle, FileCheck2, Globe2, Loader2, RotateCcw, ShieldCheck } from 'lucide-react';
import {
  applyWebsiteStaging,
  fetchWebsiteStagingWorkspace,
  rollbackWebsiteStaging,
  validateWebsiteStaging,
} from '../lib/api';
import type {
  WebsiteStagingAction,
  WebsiteStagingWorkspace,
} from '../lib/api';

export function WebsiteStagingSummary({
  workspace,
  action,
  busy = false,
  onApply = () => {},
  onDeny = () => {},
  onValidate = () => {},
  onRollback = () => {},
}: {
  workspace: WebsiteStagingWorkspace;
  action?: WebsiteStagingAction | null;
  busy?: boolean;
  onApply?: () => void;
  onDeny?: () => void;
  onValidate?: () => void;
  onRollback?: () => void;
}) {
  const { plan, execution, verification, artifact_manifest: manifest, rollback } = workspace;
  return (
    <div className="space-y-4">
      <section className="rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)' }}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">Preview diff</h3>
          <span className="rounded-full px-2 py-1 text-xs" style={{ background: 'var(--color-accent-subtle)' }}>
            Checkpoint ready
          </span>
        </div>
        <p className="mt-1 break-all text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          Preview sha256:{plan.preview_hash.slice(0, 16)}…
        </p>
        <div className="mt-3 space-y-2">
          {plan.file_diffs.map((file) => (
            <article key={file.relative_path} className="rounded-lg p-2 text-xs" style={{ border: '1px solid var(--color-border)' }}>
              <div className="flex flex-wrap justify-between gap-2">
                <strong>{file.relative_path}</strong>
                <span>{file.change} · {file.size_bytes.toLocaleString()} bytes</span>
              </div>
              <p className="mt-1 break-all" style={{ color: 'var(--color-text-secondary)' }}>
                {file.before_sha256 ? `before ${file.before_sha256.slice(0, 12)}…` : 'new file'} → {file.after_sha256.slice(0, 12)}…
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)' }}>
        <h3 className="font-semibold">Planned files</h3>
        <ul className="mt-2 space-y-1 text-xs">
          {plan.proposals.map((file) => (
            <li key={file.relative_path}>
              <FileCheck2 size={13} className="mr-2 inline" />
              {file.relative_path} · {file.media_type} · {file.size_bytes.toLocaleString()} bytes
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)' }}>
        <h3 className="font-semibold">Warnings and static scripts</h3>
        {plan.warnings.length === 0 && plan.script_files.length === 0 ? (
          <p className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>No preview warnings. JavaScript is never executed.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-xs">
            {plan.warnings.map((warning) => <li key={warning}><AlertTriangle size={13} className="mr-2 inline" />{warning}</li>)}
            {plan.script_files.map((path) => <li key={path}>Static script inventory: {path} · not executed</li>)}
          </ul>
        )}
      </section>

      {!execution && (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={onApply} className="rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
            {busy ? <Loader2 size={14} className="mr-2 inline animate-spin" /> : <ShieldCheck size={14} className="mr-2 inline" />}
            Apply now
          </button>
          <button type="button" disabled={busy} onClick={onDeny} className="rounded-lg px-3 py-2 text-sm disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
            Deny
          </button>
        </div>
      )}

      {(action || execution) && (
        <section className="rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
          <h3 className="font-semibold">Apply result</h3>
          <p className="mt-2">{action?.status || execution?.status} · {action?.verification_status || (execution ? 'passed' : 'pending')}</p>
          {execution && <p className="mt-1 break-all text-xs">Manifest sha256:{execution.artifact_manifest_sha256}</p>}
        </section>
      )}

      {verification && (
        <section className="rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
          <h3 className="font-semibold">Verification</h3>
          <p className="mt-2">{verification.status} · {verification.file_count} files · {verification.total_bytes.toLocaleString()} bytes</p>
          {verification.errors.map((error) => <p key={error} className="mt-1 text-xs" style={{ color: 'var(--color-error)' }}>{error}</p>)}
        </section>
      )}

      {manifest && (
        <section className="rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)' }}>
          <h3 className="font-semibold">Artifacts</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {manifest.artifacts.map((artifact) => (
              <li key={artifact.artifact_id}>{artifact.relative_path} · {artifact.verification_status} · sha256:{artifact.sha256.slice(0, 12)}…</li>
            ))}
          </ul>
        </section>
      )}

      {execution && !rollback && (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={onValidate} className="rounded-lg px-3 py-2 text-sm disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
            <ShieldCheck size={14} className="mr-2 inline" />Validate
          </button>
          <button type="button" disabled={busy} onClick={onRollback} className="rounded-lg px-3 py-2 text-sm disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
            <RotateCcw size={14} className="mr-2 inline" />Rollback now
          </button>
        </div>
      )}

      {rollback && (
        <section className="rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
          <h3 className="font-semibold">Rollback status</h3>
          <p className="mt-2">{rollback.byte_identical ? 'Byte-identical restore verified' : 'Rollback not verified'} · restore removed {String(rollback.restore_probe_removed)}</p>
        </section>
      )}
    </div>
  );
}

export function WebsiteStagingPanel() {
  const [workspaceId, setWorkspaceId] = useState('');
  const [workspace, setWorkspace] = useState<WebsiteStagingWorkspace | null>(null);
  const [action, setAction] = useState<WebsiteStagingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    if (!workspaceId.trim()) return;
    setBusy(true);
    setError('');
    try {
      setWorkspace(await fetchWebsiteStagingWorkspace(workspaceId.trim()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Workspace could not be loaded.');
    } finally {
      setBusy(false);
    }
  };

  const apply = async (decision: 'allow_once' | 'deny') => {
    if (!workspace) return;
    setBusy(true);
    setError('');
    try {
      const result = await applyWebsiteStaging(workspace, decision);
      setAction(result.action);
      setWorkspace(await fetchWebsiteStagingWorkspace(workspace.workspace_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Apply decision failed.');
    } finally {
      setBusy(false);
    }
  };

  const validate = async () => {
    if (!workspace?.execution) return;
    setBusy(true);
    setError('');
    try {
      const verification = await validateWebsiteStaging(workspace);
      setWorkspace({ ...workspace, verification });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Verification failed.');
    } finally {
      setBusy(false);
    }
  };

  const rollback = async () => {
    if (!workspace?.execution) return;
    setBusy(true);
    setError('');
    try {
      const result = await rollbackWebsiteStaging(workspace);
      setAction(result.action);
      setWorkspace(await fetchWebsiteStagingWorkspace(workspace.workspace_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Rollback failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="hud-panel p-4" aria-labelledby="website-staging-heading">
      <header className="mb-4">
        <p className="hud-label">WEBSITE STAGING · PHASE 8B PILOT</p>
        <h2 id="website-staging-heading" className="mt-1 font-semibold"><Globe2 size={16} className="mr-2 inline" />Isolated static website workspace</h2>
        <p className="mt-2 rounded-lg p-3 text-sm font-semibold" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}>
          Nur isolierter lokaler Workspace – keine Veröffentlichung
        </p>
      </header>
      <div className="mb-4 flex flex-wrap gap-2">
        <label htmlFor="website-workspace-id" className="sr-only">Website workspace ID</label>
        <input id="website-workspace-id" value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)} placeholder="Synthetic workspace ID" className="min-w-64 flex-1 rounded-lg px-3 py-2 text-sm" style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }} />
        <button type="button" disabled={busy || !workspaceId.trim()} onClick={() => void load()} className="rounded-lg px-3 py-2 text-sm disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
          {busy ? 'Loading…' : 'Load preview'}
        </button>
      </div>
      {error && <p role="alert" className="mb-3 text-sm" style={{ color: 'var(--color-error)' }}>{error}</p>}
      {workspace ? (
        <WebsiteStagingSummary workspace={workspace} action={action} busy={busy} onApply={() => void apply('allow_once')} onDeny={() => void apply('deny')} onValidate={() => void validate()} onRollback={() => void rollback()} />
      ) : (
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Load a previously created synthetic pilot workspace. No real project path can be entered here.</p>
      )}
    </section>
  );
}
