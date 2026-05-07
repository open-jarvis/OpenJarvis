import { useState, useEffect, useCallback } from 'react';
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { getSyncStatus } from '../../lib/connectors-api';
import { SOURCE_CATALOG } from '../../types/connectors';
import type { SyncStatus } from '../../types/connectors';

// ---------------------------------------------------------------------------
// ProgressRow
// ---------------------------------------------------------------------------

function ProgressRow({
  displayName,
  status,
}: {
  displayName: string;
  status: SyncStatus | null;
}) {
  const isDone = status?.state === 'idle' && (status?.items_synced ?? 0) > 0;
  const pct =
    status && status.items_total > 0
      ? Math.min(100, Math.round((status.items_synced / status.items_total) * 100))
      : isDone
        ? 100
        : 0;

  return (
    <div className="flex flex-col gap-1.5 p-4 rounded-xl"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {displayName}
        </span>
        <div className="flex items-center gap-1.5 shrink-0">
          {!status || status.state === 'idle' ? (
            isDone ? (
              <CheckCircle2 size={14} style={{ color: 'var(--color-accent)' }} />
            ) : (
              <Loader2 size={14} className="animate-spin" style={{ color: 'var(--color-text-tertiary)' }} />
            )
          ) : status.state === 'syncing' ? (
            <Loader2 size={14} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
          ) : status.state === 'paused' ? (
            <Loader2 size={14} style={{ color: 'var(--color-text-tertiary)' }} />
          ) : (
            <AlertCircle size={14} style={{ color: 'var(--color-error)' }} />
          )}
          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {status?.state === 'syncing'
              ? `${status.items_synced} / ${status.items_total}`
              : isDone
                ? `${status!.items_synced} items`
                : status?.state === 'paused'
                  ? 'Paused'
                  : status?.state === 'error'
                    ? 'Error'
                    : 'Starting...'}
          </span>
        </div>
      </div>
      <div
        className="h-1.5 rounded-full overflow-hidden"
        style={{ background: 'var(--color-bg-tertiary)' }}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            background:
              status?.state === 'error' ? 'var(--color-error)' : 'var(--color-accent)',
            width: `${pct}%`,
          }}
        />
      </div>
      {status?.error && (
        <p className="text-xs" style={{ color: 'var(--color-error)' }}>
          {status.error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// IngestDashboard
// ---------------------------------------------------------------------------

export function IngestDashboard({
  connectedIds,
  onReady,
}: {
  connectedIds: string[];
  onReady: () => void;
}) {
  const [statuses, setStatuses] = useState<Record<string, SyncStatus | null>>(() =>
    Object.fromEntries(connectedIds.map((id) => [id, null])),
  );

  const poll = useCallback(async () => {
    const updates = await Promise.all(
      connectedIds.map(async (id) => {
        try {
          const s = await getSyncStatus(id);
          return [id, s] as [string, SyncStatus];
        } catch {
          return [id, null] as [string, null];
        }
      }),
    );
    setStatuses(Object.fromEntries(updates));
  }, [connectedIds]);

  useEffect(() => {
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [poll]);

  const allDone = connectedIds.every(
    (id) => statuses[id]?.state === 'error' ||
      (statuses[id]?.state === 'idle' && (statuses[id]?.items_synced ?? 0) > 0),
  );

  const totalSynced = Object.values(statuses).reduce(
    (sum, s) => sum + (s?.items_synced ?? 0),
    0,
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-xl font-bold mb-1" style={{ color: 'var(--color-text)' }}>
          {allDone ? 'Sync complete' : 'Syncing your data...'}
        </h2>
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {allDone
            ? `Indexed ${totalSynced} items across ${connectedIds.length} source${connectedIds.length !== 1 ? 's' : ''}.`
            : 'This may take a few minutes depending on your data volume.'}
        </p>
      </div>

      {/* Progress rows */}
      <div className="flex flex-col gap-3 flex-1 overflow-y-auto">
        {connectedIds.map((id) => {
          const card = SOURCE_CATALOG.find((c) => c.connector_id === id);
          return (
            <ProgressRow
              key={id}
              displayName={card?.display_name ?? id}
              status={statuses[id] ?? null}
            />
          );
        })}
      </div>

      {/* Footer */}
      <div className="pt-4 border-t" style={{ borderColor: 'var(--color-border)' }}>
        <button
          onClick={onReady}
          className="w-full py-3 px-4 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-on-accent)',
          }}
        >
          {!allDone && <Loader2 size={16} className="animate-spin" />}
          Start Researching →
        </button>
        {!allDone && (
          <p className="text-center text-xs mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Sync will continue in the background
          </p>
        )}
      </div>
    </div>
  );
}
