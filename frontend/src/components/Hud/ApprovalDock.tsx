import { useEffect, useRef, useState } from 'react';
import { automationApi, type PendingApproval } from './automationApi';

const LABELS: Record<string, string> = {
  open_app: 'OPEN APPLICATION',
  open_path: 'OPEN FILE / FOLDER',
  run_pc_command: 'RUN COMMAND',
  delegate_to_claude_code: 'CLAUDE CODE TASK',
};

/**
 * Shows actions waiting for the user's yes/no (queued by PC-action tools) as
 * holographic cards. Polls quickly so a spoken request gets its card within a
 * second or two.
 */
export function ApprovalDock({
  onNew,
  onDecision,
}: {
  onNew: (a: PendingApproval) => void;
  onDecision: (a: PendingApproval, approved: boolean) => void;
}) {
  const [pending, setPending] = useState<PendingApproval[]>([]);
  const [deciding, setDeciding] = useState<string | null>(null);
  const seen = useRef(new Set<string>());
  const onNewRef = useRef(onNew);
  onNewRef.current = onNew;

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await automationApi.pendingApprovals();
        if (cancelled) return;
        const list = r.actions.filter((a) => a.action_type in LABELS);
        for (const a of list) {
          if (!seen.current.has(a.id)) {
            seen.current.add(a.id);
            onNewRef.current(a);
          }
        }
        setPending(list);
      } catch {
        /* backend offline */
      }
    };
    void poll();
    const t = setInterval(poll, 1500);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const decide = async (a: PendingApproval, approved: boolean) => {
    setDeciding(a.id);
    try {
      await (approved ? automationApi.approve(a.id) : automationApi.deny(a.id));
      setPending((p) => p.filter((x) => x.id !== a.id));
      onDecision(a, approved);
    } finally {
      setDeciding(null);
    }
  };

  if (pending.length === 0) return null;

  return (
    <div className="approval-dock" role="region" aria-label="Actions waiting for approval">
      {pending.map((a) => {
        const command = typeof a.payload?.command === 'string' ? a.payload.command : null;
        const folder = typeof a.payload?.folder === 'string' ? a.payload.folder : null;
        return (
          <div key={a.id} className="approval-card" role="alertdialog" aria-label={a.description}>
            <div className="approval-card__head">
              <span className="approval-card__badge">AUTHORISATION REQUIRED</span>
              <span className="approval-card__type">{LABELS[a.action_type]}</span>
            </div>
            <p className="approval-card__desc">{a.description}</p>
            {command && <pre className="approval-card__cmd">{command}</pre>}
            {folder && <p className="approval-card__meta">Folder: {folder}</p>}
            <div className="approval-card__actions">
              <button
                type="button"
                className="hud-btn"
                disabled={deciding === a.id}
                onClick={() => decide(a, true)}
              >
                APPROVE
              </button>
              <button
                type="button"
                className="hud-btn hud-btn--ghost"
                disabled={deciding === a.id}
                onClick={() => decide(a, false)}
              >
                DENY
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
