import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  CodexPetSpeechBubble,
  formatSpeechText,
} from './CodexPetSpeechBubble';

describe('formatSpeechText', () => {
  it('truncates text beyond maxChars with ellipsis', () => {
    expect(formatSpeechText('Ngắn', 90)).toBe('Ngắn');
    expect(formatSpeechText('A'.repeat(100), 90)).toBe('A'.repeat(87) + '...');
  });

  it('returns text as-is when within maxChars', () => {
    expect(formatSpeechText('Hello Jarvis', 20)).toBe('Hello Jarvis');
  });

  it('returns empty string for empty or undefined input', () => {
    expect(formatSpeechText('')).toBe('');
    expect(formatSpeechText(undefined)).toBe('');
    expect(formatSpeechText('   ')).toBe('');
  });
});

describe('CodexPetSpeechBubble component', () => {
  it('renders null when not visible and no active voice status or text', () => {
    const html = renderToStaticMarkup(
      React.createElement(CodexPetSpeechBubble, {})
    );
    expect(html).toBe('');
  });

  it('renders typing indicator when speaking without text', () => {
    const html = renderToStaticMarkup(
      <CodexPetSpeechBubble voiceStatus="speaking" text="" />
    );
    expect(html).toContain('data-testid="speech-bubble-typing"');
  });

  it('renders typing indicator when typing is explicitly true', () => {
    const html = renderToStaticMarkup(
      <CodexPetSpeechBubble typing={true} />
    );
    expect(html).toContain('data-testid="speech-bubble-typing"');
  });

  it('does not render when visible is explicitly false even if text is present', () => {
    const html = renderToStaticMarkup(
      <CodexPetSpeechBubble visible={false} text="Hidden message" />
    );
    expect(html).toBe('');
  });

  it('renders speech text with proper wrapping container classes', () => {
    const html = renderToStaticMarkup(
      <CodexPetSpeechBubble voiceStatus="speaking" text="Chào bạn nhé!" />
    );
    expect(html).toContain('w-max');
    expect(html).toContain('min-w-');
    expect(html).toContain('break-words');
    expect(html).toContain('Chào bạn nhé!');
  });

  it('defaults to maxChars=140 truncation in component', () => {
    const html = renderToStaticMarkup(
      <CodexPetSpeechBubble voiceStatus="speaking" text={'B'.repeat(160)} />
    );
    expect(html).toContain('B'.repeat(137) + '...');
  });

  it('applies position alignment classes for top-left and top-right', () => {
    const htmlLeft = renderToStaticMarkup(
      <CodexPetSpeechBubble text="Left bubble" position="top-left" />
    );
    expect(htmlLeft).toContain('data-position="top-left"');

    const htmlRight = renderToStaticMarkup(
      <CodexPetSpeechBubble text="Right bubble" position="top-right" />
    );
    expect(htmlRight).toContain('data-position="top-right"');
  });

  it('supports custom className and role attribute', () => {
    const html = renderToStaticMarkup(
      <CodexPetSpeechBubble
        text="Custom styled bubble"
        className="custom-bubble-class"
        role="assistant"
      />
    );
    expect(html).toContain('custom-bubble-class');
    expect(html).toContain('data-role="assistant"');
  });
});
