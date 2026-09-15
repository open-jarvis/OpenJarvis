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
  });
});
