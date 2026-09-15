import React, { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, ScreenShare, ScreenShareOff } from 'lucide-react';
import type { LocalVoiceStatus } from '@/hooks/voiceStatus';
import type { ScreenShareStatus } from '@/hooks/useScreenShare';

export interface ScreenShareDockProps {
  voiceStatus: LocalVoiceStatus;
  isVoiceActive: boolean;
  shareStatus: ScreenShareStatus;
  isShareUnavailable?: boolean;
  onToggleVoice: () => void;
  onToggleScreenShare: () => void;
  getFrequencyData?: () => Uint8Array;
  className?: string;
}

export function computeWaveformHeights(
  data: Uint8Array | undefined,
  isSpeakingOrListening: boolean,
  prevHeights: [number, number, number] = [4, 8, 4],
): [number, number, number] {
  if (!isSpeakingOrListening) {
    return [4, 8, 4];
  }
  if (!data || data.length === 0) {
    return [8, 14, 8];
  }

  const getBandAvg = (start: number, end: number): number => {
    const s = Math.min(start, data.length);
    const e = Math.min(end, data.length);
    if (e <= s) return 0;
    let sum = 0;
    for (let i = s; i < e; i++) {
      sum += data[i] ?? 0;
    }
    return sum / (e - s);
  };

  // 3 Voice Bands: Low/Bass (~100-350Hz), Mid/Formants (~350-1000Hz), High/Clarity (~1000-2500Hz)
  const v0 = getBandAvg(2, 9) / 255;
  const v1 = getBandAvg(9, 25) / 255;
  const v2 = getBandAvg(25, 55) / 255;

  const minHeight = 4;
  const maxHeight = 20;

  const target0 = Math.min(maxHeight, Math.max(minHeight, Math.round(minHeight + v0 * (maxHeight - minHeight))));
  const target1 = Math.min(maxHeight, Math.max(minHeight, Math.round(minHeight + v1 * (maxHeight - minHeight))));
  const target2 = Math.min(maxHeight, Math.max(minHeight, Math.round(minHeight + v2 * (maxHeight - minHeight))));

  // Lerp smoothing (0.4) for organic, fluid expansion and contraction
  const lerp = 0.4;
  const h0 = Math.round(prevHeights[0] + (target0 - prevHeights[0]) * lerp);
  const h1 = Math.round(prevHeights[1] + (target1 - prevHeights[1]) * lerp);
  const h2 = Math.round(prevHeights[2] + (target2 - prevHeights[2]) * lerp);

  return [h0, h1, h2];
}

export function useDockWaveform(
  getFrequencyData?: () => Uint8Array,
  isSpeakingOrListening: boolean = false,
): [number, number, number] {
  const [heights, setHeights] = useState<[number, number, number]>(() =>
    isSpeakingOrListening ? [8, 14, 8] : [4, 8, 4]
  );
  const heightsRef = useRef<[number, number, number]>(heights);
  heightsRef.current = heights;

  useEffect(() => {
    if (!isSpeakingOrListening) {
      setHeights([4, 8, 4]);
      return;
    }

    let animId: number;
    const tick = () => {
      const data = getFrequencyData ? getFrequencyData() : undefined;
      const next = computeWaveformHeights(data, isSpeakingOrListening, heightsRef.current);
      if (
        next[0] !== heightsRef.current[0] ||
        next[1] !== heightsRef.current[1] ||
        next[2] !== heightsRef.current[2]
      ) {
        setHeights(next);
      }
      animId = requestAnimationFrame(tick);
    };

    animId = requestAnimationFrame(tick);
    return () => {
      if (animId) cancelAnimationFrame(animId);
    };
  }, [getFrequencyData, isSpeakingOrListening]);

  return heights;
}

export function ScreenShareDock({
  voiceStatus,
  isVoiceActive,
  shareStatus,
  isShareUnavailable = false,
  onToggleVoice,
  onToggleScreenShare,
  getFrequencyData,
  className = '',
}: ScreenShareDockProps) {
  const isSpeakingOrListening = voiceStatus === 'listening' || voiceStatus === 'speaking';
  const isLive = shareStatus === 'live';
  const heights = useDockWaveform(getFrequencyData, isSpeakingOrListening);

  return (
    <div
      data-testid="screen-share-dock"
      className={`absolute bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 select-none ${className}`}
    >
      {/* Frosted rounded dock container */}
      <div
        className="flex items-center gap-2 p-1.5 rounded-full shadow-2xl backdrop-blur-md transition-all duration-300"
        style={{
          background: 'color-mix(in srgb, var(--color-surface) 85%, transparent)',
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
              data-testid="dock-waveform-bar-0"
              className={`w-1 rounded-full transition-all duration-75 ${
                isSpeakingOrListening
                  ? 'bg-[var(--color-accent)]'
                  : 'bg-[var(--color-text-tertiary)]'
              }`}
              style={{ height: `${heights[0]}px` }}
            />
            <span
              data-testid="dock-waveform-bar-1"
              className={`w-1 rounded-full transition-all duration-75 ${
                isSpeakingOrListening
                  ? 'bg-[var(--color-accent)]'
                  : 'bg-[var(--color-accent)]'
              }`}
              style={{ height: `${heights[1]}px` }}
            />
            <span
              data-testid="dock-waveform-bar-2"
              className={`w-1 rounded-full transition-all duration-75 ${
                isSpeakingOrListening
                  ? 'bg-[var(--color-accent)]'
                  : 'bg-[var(--color-text-tertiary)]'
              }`}
              style={{ height: `${heights[2]}px` }}
            />
          </div>

          {/* Mic action button */}
          <button
            type="button"
            data-testid="dock-mic-btn"
            onClick={onToggleVoice}
            aria-pressed={isVoiceActive}
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
          disabled={isShareUnavailable}
          onClick={isShareUnavailable ? undefined : onToggleScreenShare}
          aria-pressed={isLive}
          title={
            isShareUnavailable
              ? 'Screen sharing is unavailable on this device (Không hỗ trợ trên thiết bị này)'
              : isLive
              ? 'Stop sharing screen (Dừng chia sẻ màn hình)'
              : 'Share screen (Chia sẻ màn hình)'
          }
          aria-label={
            isShareUnavailable
              ? 'Screen sharing is unavailable on this device'
              : isLive
              ? 'Stop sharing screen'
              : 'Share screen'
          }
          className={`relative w-10 h-10 rounded-full flex items-center justify-center transition-all duration-200 ${
            isShareUnavailable
              ? 'opacity-40 cursor-not-allowed'
              : 'cursor-pointer hover:scale-105 active:scale-95'
          }`}
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
