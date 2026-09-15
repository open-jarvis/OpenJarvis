import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ScreenShareHero } from './ScreenShareHero';

describe('ScreenShareHero', () => {
  it('renders "Try Live Jarvis" title and action buttons', () => {
    const markup = renderToStaticMarkup(
      React.createElement(ScreenShareHero, {
        onStartVoice: vi.fn(),
        onStartScreenShare: vi.fn(),
        isVoiceActive: false,
      })
    );

    expect(markup).toContain('Try Live Jarvis');
    expect(markup).toContain('Talk');
    expect(markup).toContain('Share Screen');
    expect(markup).toContain('data-testid="hero-talk-btn"');
    expect(markup).toContain('data-testid="hero-share-btn"');
  });

  it('reflects active voice status label when voice is active', () => {
    const markup = renderToStaticMarkup(
      React.createElement(ScreenShareHero, {
        onStartVoice: vi.fn(),
        onStartScreenShare: vi.fn(),
        isVoiceActive: true,
      })
    );

    expect(markup).toContain('Talking...');
    expect(markup).toContain('aria-pressed="true"');
  });

  it('renders localized Vietnamese text when uiLanguage is vi', () => {
    const markup = renderToStaticMarkup(
      React.createElement(ScreenShareHero, {
        onStartVoice: vi.fn(),
        onStartScreenShare: vi.fn(),
        isVoiceActive: false,
        uiLanguage: 'vi',
      })
    );

    expect(markup).toContain('Thử Jarvis Trực Tiếp');
    expect(markup).toContain('Trò chuyện');
    expect(markup).toContain('Chia sẻ màn hình');
  });

  it('disables screen share button when isShareUnavailable is true', () => {
    const markup = renderToStaticMarkup(
      React.createElement(ScreenShareHero, {
        onStartVoice: vi.fn(),
        onStartScreenShare: vi.fn(),
        isVoiceActive: false,
        isShareUnavailable: true,
      })
    );

    expect(markup).toContain('disabled=""');
    expect(markup).toContain('opacity-40 cursor-not-allowed');
  });
});
