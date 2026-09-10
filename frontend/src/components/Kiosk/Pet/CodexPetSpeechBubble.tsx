import React from 'react';

export interface CodexPetSpeechBubbleProps {
  /** Text content to show in the speech bubble */
  text?: string;
  /** Force visibility override */
  visible?: boolean;
  /** Voice status from voice assistant (e.g. 'speaking', 'listening', 'idle') */
  voiceStatus?: string;
  /** Whether to show an animated typing/speaking indicator */
  typing?: boolean;
  /** Alignment relative to pet head */
  position?: 'top' | 'top-left' | 'top-right';
  /** Custom vertical offset in pixels above pet */
  offsetY?: number;
  /** Maximum number of characters before truncating with ellipsis */
  maxChars?: number;
  /** Additional CSS class names */
  className?: string;
  /** Additional inline styles */
  style?: React.CSSProperties;
  /** Role label */
  role?: 'assistant' | 'user' | 'system';
  /** Click handler */
  onClick?: (e: React.MouseEvent<HTMLDivElement>) => void;
}

/**
 * Formats and truncates speech text if maxChars is specified.
 */
export function formatSpeechText(text?: string, maxChars?: number): string {
  if (!text) return '';
  const trimmed = text.trim();
  if (!trimmed) return '';
  if (typeof maxChars === 'number' && maxChars > 3 && trimmed.length > maxChars) {
    return trimmed.slice(0, maxChars - 3) + '...';
  }
  return trimmed;
}

/**
 * Floating speech bubble component rendered above the Codex Pet.
 */
export function CodexPetSpeechBubble({
  text,
  visible,
  voiceStatus,
  typing = false,
  position = 'top',
  offsetY = 10,
  maxChars = 140,
  className = '',
  style,
  role = 'assistant',
  onClick,
}: CodexPetSpeechBubbleProps) {
  const formattedText = formatSpeechText(text, maxChars);
  const isSpeaking = voiceStatus === 'speaking';
  const showTyping = typing || (Boolean(voiceStatus && voiceStatus !== 'idle') && !formattedText);

  const isVisible =
    visible !== undefined
      ? visible
      : Boolean(formattedText || showTyping);

  if (!isVisible) {
    return null;
  }

  // Positioning classes
  let alignClasses = 'left-1/2 -translate-x-1/2';
  let tailClasses = 'left-1/2 -translate-x-1/2';
  if (position === 'top-left') {
    alignClasses = 'left-0';
    tailClasses = 'left-4';
  } else if (position === 'top-right') {
    alignClasses = 'right-0';
    tailClasses = 'right-4';
  }

  return (
    <div
      data-testid="codex-pet-speech-bubble"
      data-role={role}
      data-position={position}
      role="status"
      aria-live="polite"
      onClick={onClick}
      className={`absolute bottom-full mb-2 pointer-events-auto select-none z-30 transition-all duration-200 ease-out animate-in fade-in zoom-in-95 ${alignClasses} ${className}`}
      style={{
        marginBottom: `${offsetY}px`,
        ...style,
      }}
    >
      {/* Speech bubble card */}
      <div
        className="relative w-max min-w-[160px] max-w-[280px] sm:max-w-[340px] px-3.5 py-2 rounded-xl text-xs font-medium leading-snug shadow-xl backdrop-blur-md whitespace-normal break-words"
        style={{
          background: 'rgba(20, 20, 30, 0.88)',
          border: '1px solid rgba(255, 255, 255, 0.15)',
          color: '#ffffff',
          boxShadow: '0 8px 24px -4px rgba(0, 0, 0, 0.5), 0 0 12px rgba(0, 242, 254, 0.15)',
        }}
      >
        {showTyping ? (
          <div
            data-testid="speech-bubble-typing"
            className="flex items-center gap-1.5 py-0.5 px-1 justify-center"
          >
            <span
              className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce"
              style={{ animationDelay: '0ms' }}
            />
            <span
              className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce"
              style={{ animationDelay: '150ms' }}
            />
            <span
              className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce"
              style={{ animationDelay: '300ms' }}
            />
          </div>
        ) : (
          <div data-testid="speech-bubble-text" className="break-words whitespace-pre-wrap">
            {formattedText}
          </div>
        )}

        {/* Downward pointing speech tail */}
        <div
          className={`absolute -bottom-1.5 w-0 h-0 border-solid border-t-[6px] border-x-[5px] border-b-0 border-x-transparent ${tailClasses}`}
          style={{
            borderTopColor: 'rgba(20, 20, 30, 0.88)',
          }}
        />
      </div>
    </div>
  );
}
