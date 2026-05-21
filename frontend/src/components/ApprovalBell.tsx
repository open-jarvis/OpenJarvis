import { useCallback, useEffect, useRef, useState } from 'react';
import { Bell, CheckCircle, ChevronDown, ChevronUp, Clock, XCircle } from 'lucide-react';
import { approveAction, denyAction, fetchPendingApprovals } from '../lib/api';
import type { PendingApproval } from '../lib/api';

const TIER_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  trivial: { label: 'Trivial', color: 'var(--color-text-secondary)', bg: 'color-mix(in srgb, var(--color-text-secondary) 10%, transparent)' },
  low:     { label: 'Low',     color: '#3b82f6',                    bg: 'rgba(59,130,246,0.12)' },
  medium:  { label: 'Medium',  color: 'var(--color-warning)',       bg: 'color-mix(in srgb, var(--color-warning) 12%, transparent)' },
  high:    { label: 'High',    color: 'var(--color-error)',         bg: 'color-mix(in srgb, var(--color-error) 12%, transparent)' },
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function ApprovalBell() {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [processing, setProcessing] = useState<Record<string, boolean>>({});
  const containerRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setApprovals(await fetchPendingApprovals());
    } catch {
      // backend may not be running yet
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleApprove = async (id: string) => {
    setProcessing(p => ({ ...p, [id]: true }));
    try {
      await approveAction(id);
      setApprovals(prev => prev.filter(a => a.id !== id));
    } finally {
      setProcessing(p => ({ ...p, [id]: false }));
    }
  };

  const handleDeny = async (id: string) => {
    setProcessing(p => ({ ...p, [id]: true }));
    try {
      await denyAction(id);
      setApprovals(prev => prev.filter(a => a.id !== id));
    } finally {
      setProcessing(p => ({ ...p, [id]: false }));
    }
  };

  const count = approvals.length;

  return (
    <div ref={containerRef} className="fixed top-2 right-3 z-40">
      {/* Bell trigger */}
      <button
        onClick={() => setOpen(o => !o)}
        className="relative p-2 rounded-lg transition-colors cursor-pointer"
        title="Agent approvals"
        style={{
          color: count > 0 ? 'var(--color-text)' : 'var(--color-text-secondary)',
          background: open
            ? 'var(--color-bg-tertiary)'
            : count > 0
            ? 'color-mix(in srgb, var(--color-error) 8%, transparent)'
            : 'transparent',
        }}
      >
        <Bell size={17} />
        {count > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 flex items-center justify-center rounded-full text-[10px] font-bold px-1 leading-none"
            style={{ background: 'var(--color-error)', color: '#fff' }}
          >
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute right-0 top-full mt-1 rounded-xl shadow-2xl overflow-hidden flex flex-col"
          style={{
            width: '340px',
            maxHeight: '500px',
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-4 py-3 shrink-0"
            style={{ borderBottom: '1px solid var(--color-border)' }}
          >
            <div className="flex items-center gap-2">
              <Bell size={13} style={{ color: 'var(--color-accent)' }} />
              <span className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Agent Approvals
              </span>
            </div>
            {count > 0 && (
              <span
                className="text-[11px] font-medium px-2 py-0.5 rounded-full"
                style={{
                  background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
                  color: 'var(--color-error)',
                }}
              >
                {count} pending
              </span>
            )}
          </div>

          {/* Body */}
          <div className="overflow-y-auto flex-1">
            {count === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 gap-2">
                <CheckCircle size={26} style={{ color: 'var(--color-text-secondary)', opacity: 0.35 }} />
                <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  No pending approvals
                </span>
              </div>
            ) : (
              approvals.map((action, idx) => {
                const tier = TIER_STYLES[action.tier] ?? TIER_STYLES.medium;
                const isExpanded = !!expanded[action.id];
                const isLoading = !!processing[action.id];
                const hasPayload = Object.keys(action.payload ?? {}).length > 0;

                return (
                  <div
                    key={action.id}
                    className="px-4 py-3"
                    style={{
                      borderBottom: idx < count - 1 ? '1px solid var(--color-border)' : 'none',
                    }}
                  >
                    {/* Row 1: action type + tier + time */}
                    <div className="flex items-center justify-between mb-1.5">
                      <span
                        className="text-[11px] font-mono font-semibold"
                        style={{ color: 'var(--color-accent)' }}
                      >
                        {action.action_type}
                      </span>
                      <div className="flex items-center gap-2">
                        <span
                          className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
                          style={{ background: tier.bg, color: tier.color }}
                        >
                          {tier.label}
                        </span>
                        <span
                          className="text-[10px] flex items-center gap-0.5"
                          style={{ color: 'var(--color-text-secondary)' }}
                        >
                          <Clock size={9} />
                          {timeAgo(action.created_at)}
                        </span>
                      </div>
                    </div>

                    {/* Description */}
                    <p
                      className="text-[13px] mb-2.5 leading-snug"
                      style={{ color: 'var(--color-text)' }}
                    >
                      {action.description}
                    </p>

                    {/* Expandable payload */}
                    {hasPayload && (
                      <button
                        className="flex items-center gap-1 text-[11px] mb-2 cursor-pointer"
                        style={{ color: 'var(--color-text-secondary)' }}
                        onClick={() =>
                          setExpanded(e => ({ ...e, [action.id]: !e[action.id] }))
                        }
                      >
                        {isExpanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                        {isExpanded ? 'Hide details' : 'View details'}
                      </button>
                    )}

                    {isExpanded && (
                      <pre
                        className="text-[10px] rounded-lg p-2.5 mb-2.5 overflow-x-auto"
                        style={{
                          background: 'var(--color-bg-tertiary)',
                          color: 'var(--color-text-secondary)',
                          fontFamily: 'monospace',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          lineHeight: '1.5',
                        }}
                      >
                        {JSON.stringify(action.payload, null, 2)}
                      </pre>
                    )}

                    {/* Approve / Deny */}
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleApprove(action.id)}
                        disabled={isLoading}
                        className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold transition-opacity cursor-pointer disabled:opacity-40"
                        style={{
                          background: 'color-mix(in srgb, var(--color-success) 12%, transparent)',
                          color: 'var(--color-success)',
                          border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
                        }}
                      >
                        <CheckCircle size={12} />
                        Approve
                      </button>
                      <button
                        onClick={() => handleDeny(action.id)}
                        disabled={isLoading}
                        className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold transition-opacity cursor-pointer disabled:opacity-40"
                        style={{
                          background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
                          color: 'var(--color-error)',
                          border: '1px solid color-mix(in srgb, var(--color-error) 22%, transparent)',
                        }}
                      >
                        <XCircle size={12} />
                        Deny
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
