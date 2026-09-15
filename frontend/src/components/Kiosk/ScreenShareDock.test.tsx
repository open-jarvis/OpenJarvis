import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ScreenShareDock } from './ScreenShareDock';

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

  it('renders animated waveform bars when voice is speaking or listening', () => {
    const speakingMarkup = renderToStaticMarkup(
      React.createElement(ScreenShareDock, {
        voiceStatus: 'speaking',
        isVoiceActive: true,
        shareStatus: 'idle',
        onToggleVoice: vi.fn(),
        onToggleScreenShare: vi.fn(),
      })
    );

    expect(speakingMarkup).toContain('animate-pulse');
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
