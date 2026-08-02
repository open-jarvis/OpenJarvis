import type { CSSProperties } from 'react';
import type { JarvisPreferences } from './preferences';
import type { AnimationFallbackTier } from './useAnimationBudget';
import type { JarvisVoiceState, VoiceAdapterSnapshot } from './voiceAdapter';
import { CosmicField } from './CosmicField';
import './jarvis-experience.css';

const AVATAR_SRC = '/assets/jarvis/cosmic-entity-wide-v2.png';

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

export function JarvisAvatar({
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
  const mouthAllowed = fallbackTier === 1 && preferences.mouthMovement !== 'off';
  const mouthMultiplier = preferences.mouthMovement === 'normal' ? 1 : 0.55;
  const mouthOpening = voice.state === 'speaking' && voice.volumeLevel > 0.16 && mouthAllowed
    ? Math.min(2.4, (voice.volumeLevel - 0.16) * 3.2 * mouthMultiplier)
    : 0;
  const style = {
    '--jarvis-volume': voice.state === 'speaking' ? Math.max(voice.volumeLevel, 0.32).toFixed(3) : '0',
    '--jarvis-mouth-open': `${mouthOpening.toFixed(2)}px`,
  } as CSSProperties & Record<`--${string}`, string>;

  return (
    <figure
      className={`jarvis-avatar ${compact ? 'jarvis-avatar--compact' : ''}`}
      data-voice-state={voice.state}
      data-animation-tier={fallbackTier}
      data-movement={preferences.movementIntensity}
      data-mouth-active={mouthOpening > 0 ? 'true' : 'false'}
      style={style}
      aria-label={voiceStateLabel(voice.state)}
    >
      <CosmicField state={voice.state} volumeLevel={voice.volumeLevel} tier={fallbackTier} />
      <div className="jarvis-avatar__cosmos" aria-hidden="true">
        <div className="jarvis-avatar__nebula jarvis-avatar__nebula--outer" />
        <div className="jarvis-avatar__nebula jarvis-avatar__nebula--inner" />
        <div className="jarvis-avatar__stars jarvis-avatar__stars--far" />
        <div className="jarvis-avatar__stars jarvis-avatar__stars--near" />
      </div>

      <div className="jarvis-avatar__aura" aria-hidden="true" />
      <div className="jarvis-avatar__orbit jarvis-avatar__orbit--one" aria-hidden="true" />
      <div className="jarvis-avatar__orbit jarvis-avatar__orbit--two" aria-hidden="true" />
      <div className="jarvis-avatar__portrait">
        <img
          className="jarvis-avatar__image"
          src={AVATAR_SRC}
          alt="Kosmisches Jarvis-Gesicht mit schwarzen Augen"
          draggable={false}
          decoding="async"
          fetchPriority="high"
        />
        <div className="jarvis-avatar__mouth" aria-hidden="true" />
        <div className="jarvis-avatar__scan" aria-hidden="true" />
      </div>
      <div className="jarvis-avatar__voicewave" aria-hidden="true">
        {Array.from({ length: 9 }, (_, index) => <i key={index} style={{ animationDelay: `${-index * 73}ms` }} />)}
      </div>
      <div className="jarvis-avatar__rim" aria-hidden="true" />
      <figcaption className="sr-only">{voiceStateLabel(voice.state)}</figcaption>
    </figure>
  );
}
