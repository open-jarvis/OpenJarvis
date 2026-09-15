import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  FloatingCodexPet,
  fetchPetManifest,
} from './FloatingCodexPet';
import { DEFAULT_MINTY_MANIFEST } from './CodexPet';
import type { PetManifest } from './types';

const mockCustomManifest: PetManifest = {
  name: 'test-pet',
  size: { width: 32, height: 32 },
  scale: 2,
  defaultFps: 8,
  spriteUrl: '/pets/custom/sprite.png',
  columns: 4,
  rows: 4,
  animations: {
    idle: { sequence: [0, 1], frameRate: 4, loop: true },
    'running-right': { sequence: [2, 3], frameRate: 8, loop: true },
  },
};

describe('fetchPetManifest', () => {
  it('returns parsed manifest when fetch returns valid JSON', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        name: 'custom-cat',
        size: { width: 32, height: 32 },
        animations: {
          idle: [0, 1, 2],
        },
      }),
    });

    const manifest = await fetchPetManifest('/pets/custom/pet.json', mockFetch as any);
    expect(manifest.name).toBe('custom-cat');
    expect(manifest.size).toEqual({ width: 32, height: 32 });
    expect(manifest.animations.idle.sequence).toEqual([0, 1, 2]);
    expect(mockFetch).toHaveBeenCalledWith('/pets/custom/pet.json');
  });

  it('falls back to DEFAULT_MINTY_MANIFEST on HTTP 404', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
    });

    const manifest = await fetchPetManifest('/pets/missing/pet.json', mockFetch as any);
    expect(manifest).toEqual(DEFAULT_MINTY_MANIFEST);
  });

  it('falls back to DEFAULT_MINTY_MANIFEST on network throw', async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error('Network error'));

    const manifest = await fetchPetManifest('/pets/minty/pet.json', mockFetch as any);
    expect(manifest).toEqual(DEFAULT_MINTY_MANIFEST);
  });

  it('falls back to DEFAULT_MINTY_MANIFEST on invalid manifest payload', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ invalid: 'schema' }),
    });

    const manifest = await fetchPetManifest('/pets/broken/pet.json', mockFetch as any);
    expect(manifest).toEqual(DEFAULT_MINTY_MANIFEST);
  });
});

describe('FloatingCodexPet', () => {
  it('renders fixed overlay container with z-40 and default testid', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {})
    );
    expect(html).toContain('data-testid="floating-codex-pet"');
    expect(html).toContain('data-testid="codex-pet"');
    expect(html).toContain('position:fixed');
    expect(html).toContain('z-index:40');
  });

  it('accepts initial position override', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        initialPosition: { x: 500, y: 400 },
      })
    );
    expect(html).toContain('transform:translate3d(500px, 400px, 0)');
  });

  it('accepts direct manifest prop override', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        manifest: mockCustomManifest,
      })
    );
    expect(html).toContain('/pets/custom/sprite.png');
    expect(html).toContain('aria-label="Codex Pet (test-pet) - idle"');
  });

  it('resolves and renders state from voiceStatus (listening -> alert)', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        voiceStatus: 'listening',
      })
    );
    expect(html).toContain('data-state="alert"');
  });

  it('resolves and renders state from voiceStatus (speaking -> waving)', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        voiceStatus: 'speaking',
      })
    );
    expect(html).toContain('data-state="waving"');
  });

  it('resolves and renders state from voiceStatus (busy -> running-right)', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        voiceStatus: 'busy',
      })
    );
    expect(html).toContain('data-state="running-right"');
  });

  it('prioritizes activityDetail override (e.g. review)', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        voiceStatus: 'listening',
        activityDetail: 'review',
      })
    );
    expect(html).toContain('data-state="review"');
  });

  it('prioritizes activityDetail override (e.g. failed)', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        voiceStatus: 'speaking',
        activityDetail: 'failed',
      })
    );
    expect(html).toContain('data-state="failed"');
  });

  it('renders speech bubble with speechText', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        speechText: 'I am your assistant!',
      })
    );
    expect(html).toContain('data-testid="codex-pet-speech-bubble"');
    expect(html).toContain('I am your assistant!');
  });

  it('renders speech bubble with assistantCaptionText alias', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        assistantCaptionText: 'Welcome to OpenJarvis kiosk!',
      })
    );
    expect(html).toContain('data-testid="codex-pet-speech-bubble"');
    expect(html).toContain('Welcome to OpenJarvis kiosk!');
  });

  it('extracts latest sentence segment when assistantCaptionText has multiple sentences', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        voiceStatus: 'speaking',
        assistantCaptionText: 'Xin chào bạn. Tôi đang chuẩn bị đơn hàng cho bạn nhé.',
        petType: 'sprite',
      })
    );
    expect(html).toContain('Tôi đang chuẩn bị đơn hàng cho bạn nhé.');
    expect(html).not.toContain('Xin chào bạn.');
  });

  it('renders typing indicator bubble when voiceStatus is speaking and no text is provided', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        voiceStatus: 'speaking',
      })
    );
    expect(html).toContain('data-testid="codex-pet-speech-bubble"');
    expect(html).toContain('data-testid="speech-bubble-typing"');
  });

  it('merges custom className and style props', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        className: 'custom-floating-layer',
        style: { opacity: 0.95 },
      })
    );
    expect(html).toContain('custom-floating-layer');
    expect(html).toContain('opacity:0.95');
  });

  it('renders with custom scale prop', () => {
    const html = renderToStaticMarkup(
      React.createElement(FloatingCodexPet, {
        scale: 3.0,
      })
    );
    // baseWidth 110 * (3.0 / 2) = 165px
    expect(html).toContain('width:165px');
    expect(html).toContain('height:165px');
  });
});
