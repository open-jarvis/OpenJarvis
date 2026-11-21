import { useEffect } from 'react';
import { AudioLines } from 'lucide-react';
import type { HandsFreeMode } from '../../hooks/useHandsFree';

interface HandsFreeToggleProps {
  enabled: boolean;
  available: boolean;
  wakeWord: string;
  mode: HandsFreeMode;
  transcribing: boolean;
  /** Current mic RMS level, drives the pulse while listening. */
  level: number;
  /** Last transcript, shown on hover so a misheard wake word is visible. */
  heard?: string;
  onToggle: () => void;
  onStop: () => void;
}

function capitalize(word: string): string {
  return word ? word[0].toUpperCase() + word.slice(1) : word;
}

export function statusLabel(mode: HandsFreeMode, wakeWord: string, transcribing: boolean): string {
  switch (mode) {
    case 'starting':
      return 'Starting microphone…';
    case 'sleeping':
      return transcribing ? 'Hmm…' : `Say "${capitalize(wakeWord)}"`;
    case 'listening':
      return transcribing ? 'Got it…' : 'Listening…';
    case 'thinking':
      return 'Thinking… (Esc to stop)';
    case 'speaking':
      return 'Speaking… (Esc to stop)';
    case 'error':
      return 'Microphone problem';
    default:
      return 'Hands-free';
  }
}

/**
 * Pill next to Deep Research that switches hands-free voice on and off and
 * shows what the assistant is doing (waiting for its name, listening,
 * thinking, speaking).
 */
export function HandsFreeToggle({
  enabled,
  available,
  wakeWord,
  mode,
  transcribing,
  level,
  heard,
  onToggle,
  onStop,
}: HandsFreeToggleProps) {
  const busy = mode === 'thinking' || mode === 'speaking';

  useEffect(() => {
    if (!busy) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onStop();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onStop]);

  const active = enabled && available;
  const attentive = mode === 'listening' || busy;
  const color =
    mode === 'error'
      ? 'var(--color-error)'
      : attentive
        ? 'var(--color-accent)'
        : active
          ? 'var(--color-text-secondary)'
          : 'var(--color-text-tertiary)';
  // Scale the dot with the mic level while listening so it visibly reacts to speech.
  const pulse = mode === 'listening' ? 1 + Math.min(level * 25, 1.2) : 1;

  return (
    <button
      type="button"
      onClick={busy ? onStop : onToggle}
      disabled={!available}
      aria-pressed={active}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer disabled:cursor-default disabled:opacity-50"
      style={{
        background: attentive ? 'var(--color-accent-subtle)' : 'transparent',
        border: `1px solid ${attentive || mode === 'error' ? color : active ? 'var(--color-border)' : 'var(--color-border)'}`,
        color,
      }}
      title={
        !available
          ? 'Speech backend not available'
          : busy
            ? 'Stop the current reply'
            : active
              ? `Hands-free voice: on (click to turn off)${heard ? `\nLast heard: "${heard}"` : ''}`
              : `Hands-free voice: off — turn on to talk by saying "${capitalize(wakeWord)}"`
      }
    >
      {active ? (
        <span
          aria-hidden
          className="inline-block w-2 h-2 rounded-full"
          style={{
            background: color,
            transform: `scale(${pulse})`,
            transition: 'transform 120ms linear',
            animation: busy ? 'pulse 1.2s ease-in-out infinite' : 'none',
          }}
        />
      ) : (
        <AudioLines size={12} />
      )}
      {active ? statusLabel(mode, wakeWord, transcribing) : 'Hands-free'}
    </button>
  );
}
