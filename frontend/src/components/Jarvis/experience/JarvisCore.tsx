import type { CSSProperties } from 'react';
import type { JarvisPreferences } from './preferences';
import type { AnimationFallbackTier } from './useAnimationBudget';
import type { JarvisVoiceState, VoiceAdapterSnapshot } from './voiceAdapter';
import { CosmicField } from './CosmicField';
import './jarvis-experience.css';

const STATE_LABELS: Record<JarvisVoiceState, string> = {
  idle: 'Jarvis ist bereit',
  listening: 'Jarvis hört zu',
  processing: 'Jarvis verarbeitet',
  speaking: 'Jarvis spricht',
  interrupted: 'Sprachausgabe unterbrochen',
  error: 'Jarvis benötigt Aufmerksamkeit',
  offline: 'Jarvis ist offline',
  reconnecting: 'Verbindung wird wiederhergestellt',
};

export function voiceStateLabel(state: JarvisVoiceState): string {
  return STATE_LABELS[state];
}

export function JarvisCore({
  voice,
  preferences,
  fallbackTier,
  compact = false,
}: {
  voice: VoiceAdapterSnapshot;
  preferences: JarvisPreferences;
  fallbackTier: AnimationFallbackTier;
  compact?: boolean;
}) {
  const style = {
    '--jarvis-volume': Math.max(0, Math.min(1, voice.volumeLevel)).toFixed(3),
  } as CSSProperties & Record<`--${string}`, string>;

  return (
    <figure
      className={`jarvis-core ${compact ? 'jarvis-core--compact' : ''}`}
      data-voice-state={voice.state}
      data-animation-tier={fallbackTier}
      data-movement={preferences.movementIntensity}
      style={style}
      aria-label={voiceStateLabel(voice.state)}
    >
      <CosmicField state={voice.state} volumeLevel={voice.volumeLevel} tier={fallbackTier} />
      <div className="jarvis-core__halo jarvis-core__halo--outer" aria-hidden="true" />
      <div className="jarvis-core__halo jarvis-core__halo--inner" aria-hidden="true" />
      <div className="jarvis-core__sphere" aria-hidden="true">
        <div className="jarvis-core__dust jarvis-core__dust--north" />
        <div className="jarvis-core__dust jarvis-core__dust--west" />
        <div className="jarvis-core__dust jarvis-core__dust--south" />
        <div className="jarvis-core__light" />
      </div>
      <div className="jarvis-core__orbit jarvis-core__orbit--one" aria-hidden="true" />
      <div className="jarvis-core__orbit jarvis-core__orbit--two" aria-hidden="true" />
      <figcaption className="sr-only">{voiceStateLabel(voice.state)}</figcaption>
    </figure>
  );
}
