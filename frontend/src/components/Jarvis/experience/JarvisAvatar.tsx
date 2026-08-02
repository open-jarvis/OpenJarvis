import type { CSSProperties } from 'react';
import type { JarvisPreferences } from './preferences';
import type { AnimationFallbackTier } from './useAnimationBudget';
import type { JarvisVoiceState, VoiceAdapterSnapshot } from './voiceAdapter';
import './jarvis-experience.css';

const AVATAR_SRC = '/assets/jarvis/cosmic-face.png';

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

const PARTICLES = [
  [9, 18, 0.7], [17, 69, 0.45], [24, 33, 0.55], [31, 82, 0.6], [38, 13, 0.4],
  [44, 74, 0.7], [52, 22, 0.5], [58, 88, 0.4], [66, 16, 0.65], [73, 72, 0.55],
  [81, 31, 0.45], [89, 63, 0.65], [14, 48, 0.35], [35, 57, 0.4], [63, 46, 0.35],
  [84, 87, 0.45],
] as const;

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
    '--jarvis-volume': voice.state === 'speaking' ? voice.volumeLevel.toFixed(3) : '0',
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
      <div className="jarvis-avatar__cosmos" aria-hidden="true">
        <div className="jarvis-avatar__nebula jarvis-avatar__nebula--outer" />
        <div className="jarvis-avatar__nebula jarvis-avatar__nebula--inner" />
        <div className="jarvis-avatar__stars jarvis-avatar__stars--far" />
        <div className="jarvis-avatar__stars jarvis-avatar__stars--near" />
        <div className="jarvis-avatar__particles">
          {PARTICLES.map(([left, top, opacity], index) => (
            <i
              key={`${left}-${top}`}
              style={{
                left: `${left}%`,
                top: `${top}%`,
                opacity,
                animationDelay: `${-index * 0.41}s`,
              }}
            />
          ))}
        </div>
      </div>

      <div className="jarvis-avatar__aura" aria-hidden="true" />
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
      </div>
      <div className="jarvis-avatar__rim" aria-hidden="true" />
      <figcaption className="sr-only">{voiceStateLabel(voice.state)}</figcaption>
    </figure>
  );
}
