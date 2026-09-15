import React from 'react';
import { Mic, MicOff, ScreenShare, ScreenShareOff } from 'lucide-react';
import type { LocalVoiceStatus } from '@/hooks/voiceStatus';
import type { ScreenShareStatus } from '@/hooks/useScreenShare';

export interface ScreenShareDockProps {
  voiceStatus: LocalVoiceStatus;
  isVoiceActive: boolean;
  shareStatus: ScreenShareStatus;
  onToggleVoice: () => void;
  onToggleScreenShare: () => void;
  className?: string;
}

export function ScreenShareDock({
  voiceStatus,
  isVoiceActive,
  shareStatus,
  onToggleVoice,
  onToggleScreenShare,
  className = '',
}: ScreenShareDockProps) {
  const isSpeakingOrListening = voiceStatus === 'listening' || voiceStatus === 'speaking';
  const isLive = shareStatus === 'live';

  return (
    <div
      data-testid="screen-share-dock"
      className={`absolute bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 select-none ${className}`}
    >
      {/* Frosted rounded dock container */}
      <div
        className="flex items-center gap-2 p-1.5 rounded-full shadow-2xl backdrop-blur-md transition-all duration-300"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: '0 20px 40px -10px rgba(0,0,0,0.25)',
        }}
      >
        {/* 1. Mic + Audio Waveform Pill */}
        <div
          className="flex items-center gap-2 pl-3 pr-1 py-1 rounded-full transition-colors"
          style={{
            background: 'var(--color-bg-secondary)',
          }}
        >
          {/* 3-Bar animated audio equalizer */}
          <div
            data-testid="dock-waveform"
            className="flex items-center gap-1 h-5 w-7 justify-center"
            aria-hidden="true"
          >
            <span
              className={`w-1 rounded-full transition-all duration-200 ${
                isSpeakingOrListening
                  ? 'h-4 bg-[var(--color-accent)] animate-pulse'
                  : 'h-1.5 bg-[var(--color-text-tertiary)]'
              }`}
              style={{ animationDelay: '0ms' }}
            />
            <span
              className={`w-1 rounded-full transition-all duration-200 ${
                isSpeakingOrListening
                  ? 'h-5 bg-[var(--color-accent)] animate-pulse'
                  : 'h-3 bg-[var(--color-accent)]'
              }`}
              style={{ animationDelay: '150ms' }}
            />
            <span
              className={`w-1 rounded-full transition-all duration-200 ${
                isSpeakingOrListening
                  ? 'h-3.5 bg-[var(--color-accent)] animate-pulse'
                  : 'h-1.5 bg-[var(--color-text-tertiary)]'
              }`}
              style={{ animationDelay: '300ms' }}
            />
          </div>

          {/* Mic action button */}
          <button
            type="button"
            data-testid="dock-mic-btn"
            onClick={onToggleVoice}
            title={isVoiceActive ? 'Stop voice (Dừng hội thoại)' : 'Start voice (Bật hội thoại)'}
            aria-label={isVoiceActive ? 'Stop voice' : 'Start voice'}
            className="w-8 h-8 rounded-full flex items-center justify-center cursor-pointer transition-all duration-200 hover:scale-105 active:scale-95"
            style={{
              background: isVoiceActive ? 'var(--color-accent)' : 'var(--color-surface)',
              color: isVoiceActive ? 'var(--color-text-inverse, #ffffff)' : 'var(--color-text)',
              border: isVoiceActive ? 'none' : '1px solid var(--color-border)',
            }}
          >
            {isVoiceActive ? <Mic size={15} /> : <MicOff size={15} />}
          </button>
        </div>

        {/* 2. Screen Share Toggle Button */}
        <button
          type="button"
          data-testid="dock-share-btn"
          onClick={onToggleScreenShare}
          title={isLive ? 'Stop sharing screen' : 'Share screen'}
          aria-label={isLive ? 'Stop sharing screen' : 'Share screen'}
          className="relative w-10 h-10 rounded-full flex items-center justify-center cursor-pointer transition-all duration-200 hover:scale-105 active:scale-95"
          style={{
            background: isLive ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
            color: isLive ? 'var(--color-text-inverse, #ffffff)' : 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
        >
          {isLive ? <ScreenShareOff size={16} /> : <ScreenShare size={16} />}

          {/* Live indicator dot badge */}
          {isLive && (
            <span
              data-testid="dock-live-badge"
              className="absolute top-1 right-1 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-[var(--color-surface)] animate-pulse"
            />
          )}
        </button>
      </div>
    </div>
  );
}
