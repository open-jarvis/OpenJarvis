import React from 'react';
import { Mic, ScreenShare } from 'lucide-react';

export interface ScreenShareHeroProps {
  onStartVoice: () => void;
  onStartScreenShare: () => void;
  isVoiceActive?: boolean;
  className?: string;
}

export function ScreenShareHero({
  onStartVoice,
  onStartScreenShare,
  isVoiceActive = false,
  className = '',
}: ScreenShareHeroProps) {
  return (
    <div
      data-testid="screen-share-hero"
      className={`absolute inset-0 flex flex-col items-center justify-center pointer-events-none select-none z-10 px-4 ${className}`}
    >
      <div className="flex flex-col items-center text-center max-w-lg gap-6 pointer-events-auto">
        {/* Hero Title */}
        <h1
          className="text-3xl sm:text-4xl font-semibold tracking-tight"
          style={{ color: 'var(--color-text)' }}
        >
          Try Live Jarvis
        </h1>

        {/* Action Pills Row */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            data-testid="hero-talk-btn"
            onClick={onStartVoice}
            className="flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium cursor-pointer transition-all duration-200 hover:scale-105 active:scale-95 shadow-md"
            style={{
              background: isVoiceActive ? 'var(--color-accent)' : 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              color: isVoiceActive ? 'var(--color-text-inverse, #ffffff)' : 'var(--color-text)',
            }}
          >
            <Mic size={16} className={isVoiceActive ? 'animate-pulse' : ''} />
            <span>{isVoiceActive ? 'Talking...' : 'Talk'}</span>
          </button>

          <button
            type="button"
            data-testid="hero-share-btn"
            onClick={onStartScreenShare}
            className="flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium cursor-pointer transition-all duration-200 hover:scale-105 active:scale-95 shadow-md"
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
          >
            <ScreenShare size={16} />
            <span>Share Screen</span>
          </button>
        </div>
      </div>
    </div>
  );
}
