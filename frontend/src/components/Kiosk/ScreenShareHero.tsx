import React from 'react';
import { Mic, ScreenShare } from 'lucide-react';

export interface ScreenShareHeroProps {
  onStartVoice: () => void;
  onStartScreenShare: () => void;
  isVoiceActive?: boolean;
  isShareUnavailable?: boolean;
  uiLanguage?: string;
  className?: string;
}

export function ScreenShareHero({
  onStartVoice,
  onStartScreenShare,
  isVoiceActive = false,
  isShareUnavailable = false,
  uiLanguage = 'en',
  className = '',
}: ScreenShareHeroProps) {
  const isVi = uiLanguage === 'vi';

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
          {isVi ? 'Thử Jarvis Trực Tiếp' : 'Try Live Jarvis'}
        </h1>

        {/* Action Pills Row */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            data-testid="hero-talk-btn"
            onClick={onStartVoice}
            aria-pressed={isVoiceActive}
            className="flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium cursor-pointer transition-all duration-200 hover:scale-105 active:scale-95 shadow-md"
            style={{
              background: isVoiceActive ? 'var(--color-accent)' : 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              color: isVoiceActive ? 'var(--color-text-inverse, #ffffff)' : 'var(--color-text)',
            }}
          >
            <Mic size={16} className={isVoiceActive ? 'animate-pulse' : ''} />
            <span>{isVoiceActive ? (isVi ? 'Đang nói...' : 'Talking...') : (isVi ? 'Trò chuyện' : 'Talk')}</span>
          </button>

          <button
            type="button"
            data-testid="hero-share-btn"
            disabled={isShareUnavailable}
            onClick={isShareUnavailable ? undefined : onStartScreenShare}
            title={
              isShareUnavailable
                ? (isVi ? 'Chia sẻ màn hình không khả dụng trên thiết bị này' : 'Screen sharing is unavailable on this device')
                : (isVi ? 'Chia sẻ màn hình' : 'Share Screen')
            }
            className={`flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium transition-all duration-200 shadow-md ${
              isShareUnavailable
                ? 'opacity-40 cursor-not-allowed'
                : 'cursor-pointer hover:scale-105 active:scale-95'
            }`}
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
          >
            <ScreenShare size={16} />
            <span>{isVi ? 'Chia sẻ màn hình' : 'Share Screen'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
