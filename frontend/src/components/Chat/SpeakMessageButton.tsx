import { Volume2, Square } from 'lucide-react';
import { useTts } from '../../hooks/useTts';
import { useAppStore } from '../../lib/store';

interface Props {
  messageId: string;
  content: string;
}

/** Reads one assistant message aloud through the server's TTS backend. */
export function SpeakMessageButton({ messageId, content }: Props) {
  const voiceOutputEnabled = useAppStore((s) => s.settings.voiceOutputEnabled);
  const { speak, stop, speakingId, available, state, error } = useTts();

  if (!voiceOutputEnabled || !available) return null;

  // Playback is global, so this button reflects the shared utterance only when
  // that utterance is this message.
  const isMine = speakingId === messageId;
  const busy = isMine && (state === 'loading' || state === 'speaking');

  return (
    <button
      onClick={() => (busy ? stop() : speak(messageId, content))}
      className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
      style={{
        color: busy ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
        opacity: busy ? 1 : undefined,
      }}
      title={
        (isMine && error) ||
        (isMine && state === 'loading'
          ? 'Synthesizing...'
          : isMine && state === 'speaking'
            ? 'Stop'
            : 'Read aloud')
      }
      aria-label={busy ? 'Stop reading message' : 'Read message aloud'}
    >
      {busy ? <Square size={14} /> : <Volume2 size={14} />}
    </button>
  );
}
