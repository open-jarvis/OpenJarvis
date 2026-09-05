import { Volume2, Square } from 'lucide-react';
import { useTts } from '../../hooks/useTts';
import { useAppStore } from '../../lib/store';

/** Reads one assistant message aloud through the server's TTS backend. */
export function SpeakMessageButton({ content }: { content: string }) {
  const voiceOutputEnabled = useAppStore((s) => s.settings.voiceOutputEnabled);
  const { speak, stop, available, isLoading, isSpeaking, error } = useTts();

  if (!voiceOutputEnabled || !available) return null;

  const busy = isLoading || isSpeaking;

  return (
    <button
      onClick={() => (busy ? stop() : speak(content))}
      className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
      style={{
        color: busy ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
        opacity: busy ? 1 : undefined,
      }}
      title={
        error ??
        (isLoading ? 'Synthesizing...' : isSpeaking ? 'Stop' : 'Read aloud')
      }
      aria-label={busy ? 'Stop reading message' : 'Read message aloud'}
    >
      {busy ? <Square size={14} /> : <Volume2 size={14} />}
    </button>
  );
}
