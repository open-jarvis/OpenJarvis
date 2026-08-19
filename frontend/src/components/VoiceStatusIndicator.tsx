import { useEffect, useState } from 'react';
import { Mic } from 'lucide-react';
import { fetchVoiceStatus, type VoiceStatus } from '../lib/api';
import { useAppStore } from '../lib/store';

// Always-visible widget reflecting the background wake-word listener's
// state. Polls the backend (the listener runs inside `jarvis serve`,
// independent of this window's focus) — this is a status *display* only,
// it never captures audio itself. Distinct from the push-to-talk
// MicButton in the chat input, which is unaffected by this component.
export function VoiceStatusIndicator() {
  const wakeWordEnabled = useAppStore((s) => s.settings.wakeWordEnabled);
  const [status, setStatus] = useState<VoiceStatus | null>(null);

  useEffect(() => {
    if (!wakeWordEnabled) return;
    const poll = () => fetchVoiceStatus().then(setStatus).catch(() => setStatus(null));
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [wakeWordEnabled]);

  if (!wakeWordEnabled) return null;
  if (!status?.available) {
    return (
      <div
        className="flex items-center gap-2 px-3 py-1.5 text-xs"
        style={{ color: 'var(--color-text-tertiary)' }}
        title="Wake-word listener not running (check jarvis serve + voice.enabled in config.toml)"
      >
        <Mic size={12} />
        <span className="hud-mono">voice offline</span>
      </div>
    );
  }

  const state = status.state ?? 'idle';
  const isActive = state === 'wake_detected' || state === 'transcribing' || state === 'replying';

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 text-xs"
      style={{ color: 'var(--color-text-secondary)' }}
      title={`Wake-word listener: ${state}`}
    >
      {isActive ? (
        <span className="hud-reticle" style={{ width: 14, height: 14 }} />
      ) : (
        <span className="hud-heartbeat" />
      )}
      <span className="hud-mono uppercase">{state}</span>
    </div>
  );
}
