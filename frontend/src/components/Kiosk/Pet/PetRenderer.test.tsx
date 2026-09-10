import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { PetRenderer, isWebGLSupported } from './PetRenderer';
import { DEFAULT_MINTY_MANIFEST } from './CodexPet';

describe('PetRenderer', () => {
  it('detects webgl support function', () => {
    expect(typeof isWebGLSupported()).toBe('boolean');
  });

  it('renders 3D robot mascot by default when petType is robot', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'robot',
        state: 'idle',
      })
    );
    expect(html).toContain('data-testid="codex-pet"');
    expect(html).toContain('data-mascot="robot"');
    expect(html).toContain('data-testid="robot-pet"');
  });

  it('renders legacy 2D sprite pet when petType is sprite', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'sprite',
        manifest: DEFAULT_MINTY_MANIFEST,
        state: 'idle',
      })
    );
    expect(html).toContain('data-testid="codex-pet"');
    expect(html).not.toContain('data-mascot="robot"');
    expect(html).toContain('/pets/minty/sprite.png');
  });

  it('renders speech bubble with speechText in 3D robot mode', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'robot',
        speechText: 'Hello from 3D Robot!',
      })
    );
    expect(html).toContain('data-testid="codex-pet-speech-bubble"');
    expect(html).toContain('Hello from 3D Robot!');
  });

  it('renders speech bubble when voiceStatus is speaking', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'robot',
        voiceStatus: 'speaking',
      })
    );
    expect(html).toContain('data-testid="codex-pet-speech-bubble"');
    expect(html).toContain('data-testid="speech-bubble-typing"');
  });

  it('syncs state to robot mascot (listening -> alert)', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'robot',
        state: 'alert',
      })
    );
    expect(html).toContain('data-state="alert"');
    expect(html).not.toContain('ring-2');
  });

  it('syncs state to robot mascot (speaking -> waving)', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'robot',
        state: 'speaking',
      })
    );
    expect(html).toContain('data-state="speaking"');
    expect(html).not.toContain('ring-1');
  });

  it('syncs state to robot mascot (success/review -> celebratory bounce)', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'robot',
        state: 'review',
      })
    );
    expect(html).toContain('data-state="review"');
    expect(html).toContain('animate-[bounce_1.5s_infinite]');
  });

  it('syncs state to robot mascot (error/failed -> warning reaction)', () => {
    const html = renderToStaticMarkup(
      React.createElement(PetRenderer, {
        petType: 'robot',
        state: 'failed',
      })
    );
    expect(html).toContain('data-state="failed"');
    expect(html).not.toContain('ring-2');
  });
});
