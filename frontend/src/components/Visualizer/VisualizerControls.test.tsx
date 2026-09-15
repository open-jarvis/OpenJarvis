import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { VisualizerControls } from './VisualizerControls';
import { VISUALIZER_DEFAULTS } from './types';

describe('VisualizerControls', () => {
  it('renders collapsed settings toggle button by default', () => {
    const markup = renderToStaticMarkup(
      React.createElement(VisualizerControls, {
        settings: VISUALIZER_DEFAULTS,
        onSettingsChange: vi.fn(),
        status: 'idle',
        uiLanguage: 'vi',
        onUiLanguageChange: vi.fn(),
      })
    );

    expect(markup).toContain('title="Open panel"');
  });

  it('renders uncollapsed panel with Show Mascot toggle and Pet Size slider', () => {
    const markup = renderToStaticMarkup(
      React.createElement(VisualizerControls, {
        settings: {
          ...VISUALIZER_DEFAULTS,
          showPet: true,
          petScale: 2.5,
        },
        onSettingsChange: vi.fn(),
        status: 'idle',
        uiLanguage: 'vi',
        onUiLanguageChange: vi.fn(),
        initialCollapsed: false,
      })
    );

    expect(markup).toContain('Show Captions');
    expect(markup).toContain('Show Mascot');
    expect(markup).toContain('Pet Size');
    expect(markup).toContain('2.5x');
    expect(markup).toContain('min="1"');
    expect(markup).toContain('max="4"');
    expect(markup).toContain('step="0.1"');
  });

  it('reflects updated petScale in slider output label', () => {
    const markup = renderToStaticMarkup(
      React.createElement(VisualizerControls, {
        settings: {
          ...VISUALIZER_DEFAULTS,
          showPet: false,
          petScale: 3.4,
        },
        onSettingsChange: vi.fn(),
        status: 'listening',
        uiLanguage: 'en',
        onUiLanguageChange: vi.fn(),
        initialCollapsed: false,
      })
    );

    expect(markup).toContain('3.4x');
  });

  it('renders all three modular card sections with setting rows matching chat mode template', () => {
    const markup = renderToStaticMarkup(
      React.createElement(VisualizerControls, {
        settings: VISUALIZER_DEFAULTS,
        onSettingsChange: vi.fn(),
        status: 'speaking',
        uiLanguage: 'vi',
        onUiLanguageChange: vi.fn(),
        initialCollapsed: false,
      })
    );

    // Three distinct card sections
    expect(markup).toContain('Language');
    expect(markup).toContain('Visualizer &amp; Display');
    expect(markup).toContain('Mascot &amp; Captions');

    // Setting rows in Language
    expect(markup).not.toContain('Voice status');
    expect(markup).toContain('Language');

    // Setting rows in Visualizer & Display
    expect(markup).toContain('Display mode');
    expect(markup).toContain('Screen Share');
    expect(markup).toContain('3D Sphere');
    expect(markup).toContain('Theme');
    expect(markup).toContain('Size');
    expect(markup).toContain('Gain');
    expect(markup).toContain('Speed');
    expect(markup).toContain('Glow');

    // Setting rows in Mascot & Captions
    expect(markup).toContain('Show Captions');
    expect(markup).toContain('Show Mascot');
    expect(markup).toContain('Pet Size');
  });

  it('renders centered popup dialog with [X] close button matching chatgpt modal style', () => {
    const markup = renderToStaticMarkup(
      React.createElement(VisualizerControls, {
        settings: VISUALIZER_DEFAULTS,
        onSettingsChange: vi.fn(),
        status: 'idle',
        uiLanguage: 'vi',
        onUiLanguageChange: vi.fn(),
        initialCollapsed: false,
      })
    );

    // Centered modal overlay & dialog
    expect(markup).toContain('fixed inset-0');
    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('title="Close"');
    expect(markup).toContain('aria-label="Close"');
    expect(markup).not.toContain('Hide');
  });
});
