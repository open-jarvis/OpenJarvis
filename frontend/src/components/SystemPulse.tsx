import { useEffect, useState } from 'react';
import { useAppStore } from '../lib/store';
import { fetchManagedAgents } from '../lib/api';

type PulseState = 'idle' | 'inferencing' | 'agent-active' | 'hidden';

const PULSE_CONFIG: Record<Exclude<PulseState, 'hidden'>, { color: string; animation: string }> = {
  idle: {
    color: 'color-mix(in srgb, var(--color-accent) 22%, transparent)',
    animation: 'none',
  },
  inferencing: {
    color: 'var(--color-accent)',
    animation: 'pulse-glow 2s ease-in-out infinite',
  },
  'agent-active': {
    color: 'var(--color-accent-purple)',
    animation: 'pulse-travel 3s linear infinite',
  },
};

export function SystemPulse({ apiReachable }: { apiReachable: boolean | null }) {
  const isStreaming = useAppStore((s) => s.streamState.isStreaming);
  const [hasRunningAgent, setHasRunningAgent] = useState(false);

  // Poll for running agents every 30s
  useEffect(() => {
    if (apiReachable === false) return;
    const check = () =>
      fetchManagedAgents()
        .then((agents) => setHasRunningAgent(agents.some((a) => a.status === 'running')))
        .catch(() => {});
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, [apiReachable]);

  if (apiReachable === false) return null;

  // Priority: agent-active > inferencing > idle
  let state: PulseState = 'idle';
  if (isStreaming) state = 'inferencing';
  if (hasRunningAgent) state = 'agent-active';

  const config = PULSE_CONFIG[state];
  const isTravel = state === 'agent-active';

  return (
    <div
      className="fixed top-0 left-0 right-0 h-[3px] z-50"
      style={{
        background: isTravel
          ? `linear-gradient(90deg, transparent, ${config.color}, transparent)`
          : `linear-gradient(90deg, transparent 5%, ${config.color} 30%, ${config.color} 70%, transparent 95%)`,
        backgroundSize: isTravel ? '200% 100%' : '100% 100%',
        animation: config.animation,
      }}
    />
  );
}
