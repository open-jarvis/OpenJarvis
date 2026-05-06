// Renders the queued proactive elaborations from Claude-CLI.
// Each item shows: "Sir, regarding earlier — '<question excerpt>' —
// may I elaborate?" with [Yes] / [Not now] buttons. Once accepted, the
// claude_answer arrives via SSE and is displayed inline + spoken.

import { useEffect, useRef } from 'react';
import { Sparkles, X } from 'lucide-react';
import { useAppStore } from '../lib/store';
import {
  acceptElaboration,
  dismissElaboration,
} from '../lib/elaborations';
import { speak as ttsSpeak, isSupported as ttsSupported } from '../lib/tts';

export function ElaborationBanner() {
  const proposals = useAppStore((s) => s.proposedElaborations);
  const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
  const removeElaboration = useAppStore((s) => s.removeElaboration);
  const announcedRef = useRef<Set<string>>(new Set());

  // Speak the "may I elaborate?" prompt once per proposal.
  useEffect(() => {
    if (!speechEnabled || !ttsSupported()) return;
    for (const p of proposals) {
      if (p.ui_state === 'proposed' && !announcedRef.current.has(p.id)) {
        announcedRef.current.add(p.id);
        const excerpt =
          p.original_question_excerpt.length > 60
            ? p.original_question_excerpt.slice(0, 60) + '...'
            : p.original_question_excerpt;
        ttsSpeak(
          `Sir, regarding your earlier question — ${excerpt} — may I elaborate?`,
        );
      }
    }
  }, [proposals, speechEnabled]);

  // Speak the elaboration text once it resolves.
  const resolvedAnnouncedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!speechEnabled || !ttsSupported()) return;
    for (const p of proposals) {
      if (
        p.ui_state === 'resolved' &&
        p.claude_answer &&
        !resolvedAnnouncedRef.current.has(p.id)
      ) {
        resolvedAnnouncedRef.current.add(p.id);
        ttsSpeak(p.claude_answer);
      }
    }
  }, [proposals, speechEnabled]);

  if (!proposals.length) return null;

  const handleAccept = async (id: string) => {
    // Local optimistic state
    useAppStore.setState((s) => ({
      proposedElaborations: s.proposedElaborations.map((e) =>
        e.id === id ? { ...e, ui_state: 'accepting' } : e,
      ),
    }));
    try {
      await acceptElaboration(id);
    } catch (exc) {
      console.warn('[elaborations] accept failed', exc);
    }
  };

  const handleDismiss = async (id: string) => {
    removeElaboration(id);
    try {
      await dismissElaboration(id);
    } catch {}
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: '8px 16px',
        borderTop: '1px solid var(--color-border)',
        borderBottom: '1px solid var(--color-border)',
        background:
          'color-mix(in srgb, var(--color-accent) 6%, transparent)',
      }}
    >
      {proposals.map((p) => (
        <div
          key={p.id}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
            padding: 12,
            borderRadius: 8,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <Sparkles
            size={18}
            style={{ color: 'var(--color-accent)', marginTop: 2, flexShrink: 0 }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            {p.ui_state === 'resolved' && p.claude_answer ? (
              <>
                <div
                  style={{
                    fontSize: 11,
                    color: 'var(--color-text-tertiary)',
                    marginBottom: 4,
                  }}
                >
                  Claude elaborates on: "{p.original_question_excerpt}"
                </div>
                <div
                  style={{
                    fontSize: 14,
                    color: 'var(--color-text)',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {p.claude_answer}
                </div>
              </>
            ) : (
              <>
                <div
                  style={{
                    fontSize: 13,
                    color: 'var(--color-text)',
                    marginBottom: 8,
                  }}
                >
                  Sir, regarding your earlier question — "
                  <em>{p.original_question_excerpt}</em>" — may I elaborate?
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => handleAccept(p.id)}
                    disabled={p.ui_state === 'accepting'}
                    style={{
                      padding: '4px 12px',
                      borderRadius: 6,
                      background: 'var(--color-accent)',
                      color: 'var(--color-on-accent)',
                      border: 'none',
                      fontSize: 12,
                      cursor:
                        p.ui_state === 'accepting' ? 'wait' : 'pointer',
                      opacity: p.ui_state === 'accepting' ? 0.7 : 1,
                    }}
                  >
                    {p.ui_state === 'accepting'
                      ? 'Elaborating…'
                      : 'Yes, please'}
                  </button>
                  <button
                    onClick={() => handleDismiss(p.id)}
                    style={{
                      padding: '4px 12px',
                      borderRadius: 6,
                      background: 'transparent',
                      color: 'var(--color-text-tertiary)',
                      border: '1px solid var(--color-border)',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                  >
                    Not now
                  </button>
                </div>
              </>
            )}
          </div>
          {p.ui_state === 'resolved' && (
            <button
              onClick={() => removeElaboration(p.id)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--color-text-tertiary)',
                cursor: 'pointer',
                padding: 4,
              }}
              aria-label="Dismiss"
            >
              <X size={14} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
