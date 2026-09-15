import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ScreenShareDock, computeWaveformHeights } from './ScreenShareDock';

describe('ScreenShareDock', () => {
  it('renders floating dock with mic pill and screen share toggle button', () => {
    const markup = renderToStaticMarkup(
      React.createElement(ScreenShareDock, {
        voiceStatus: 'idle',
        isVoiceActive: false,
        shareStatus: 'idle',
        onToggleVoice: vi.fn(),
        onToggleScreenShare: vi.fn(),
      })
    );

    expect(markup).toContain('data-testid="screen-share-dock"');
    expect(markup).toContain('data-testid="dock-mic-btn"');
    expect(markup).toContain('data-testid="dock-waveform"');
    expect(markup).toContain('data-testid="dock-share-btn"');
  });

  it('renders reactive waveform bars when voice is speaking or listening', () => {
    const speakingMarkup = renderToStaticMarkup(
      React.createElement(ScreenShareDock, {
        voiceStatus: 'speaking',
        isVoiceActive: true,
        shareStatus: 'idle',
        onToggleVoice: vi.fn(),
        onToggleScreenShare: vi.fn(),
      })
    );

    expect(speakingMarkup).toContain('data-testid="dock-waveform-bar-0"');
    expect(speakingMarkup).toContain('data-testid="dock-waveform-bar-1"');
    expect(speakingMarkup).toContain('data-testid="dock-waveform-bar-2"');
    expect(speakingMarkup).toContain('bg-[var(--color-accent)]');
  });

  it('computes idle bar heights when not speaking or listening', () => {
    expect(computeWaveformHeights(new Uint8Array([255, 255]), false)).toEqual([4, 8, 4]);
  });

  it('computes dynamic reactive bar heights from frequency data when speaking', () => {
    const data = new Uint8Array(64);
    // Fill bass with high volume, mid with low volume, high with medium volume
    for (let i = 2; i < 9; i++) data[i] = 255;
    for (let i = 9; i < 25; i++) data[i] = 40;
    for (let i = 25; i < 55; i++) data[i] = 180;

    const heights = computeWaveformHeights(data, true, [4, 4, 4]);
    expect(heights[0]).toBeGreaterThan(heights[1]);
    expect(heights[0]).toBeGreaterThan(4);
    expect(heights[2]).toBeGreaterThan(heights[1]);
  });

  it('renders active live dot badge when screen share is live', () => {
    const liveMarkup = renderToStaticMarkup(
      React.createElement(ScreenShareDock, {
        voiceStatus: 'idle',
        isVoiceActive: false,
        shareStatus: 'live',
        onToggleVoice: vi.fn(),
        onToggleScreenShare: vi.fn(),
      })
    );

    expect(liveMarkup).toContain('data-testid="dock-live-badge"');
    expect(liveMarkup).toContain('bg-emerald-400');
    expect(liveMarkup).toContain('aria-pressed="true"');
  });

  it('renders frosted glass backdrop with alpha-blended surface background', () => {
    const markup = renderToStaticMarkup(
      React.createElement(ScreenShareDock, {
        voiceStatus: 'idle',
        isVoiceActive: false,
        shareStatus: 'idle',
        onToggleVoice: vi.fn(),
        onToggleScreenShare: vi.fn(),
      })
    );

    expect(markup).toContain('backdrop-blur-md');
    expect(markup).toContain('color-mix(in srgb, var(--color-surface) 85%, transparent)');
  });

  it('disables screen share button when isShareUnavailable is true', () => {
    const markup = renderToStaticMarkup(
      React.createElement(ScreenShareDock, {
        voiceStatus: 'idle',
        isVoiceActive: false,
        shareStatus: 'idle',
        isShareUnavailable: true,
        onToggleVoice: vi.fn(),
        onToggleScreenShare: vi.fn(),
      })
    );

    expect(markup).toContain('disabled=""');
    expect(markup).toContain('opacity-40 cursor-not-allowed');
  });
});
