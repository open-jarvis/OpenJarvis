import { describe, expect, it } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ScreenShareView } from './ScreenShareView';

describe('ScreenShareView', () => {
  it('renders non-floating video container when floating is false', () => {
    const html = renderToStaticMarkup(
      React.createElement(ScreenShareView, { stream: null, floating: false }),
    );
    expect(html).toContain('<video');
    expect(html).toContain('absolute inset-0 h-full w-full');
    expect(html).not.toContain('data-testid="screen-share-view"');
  });

  it('renders floating card with 4 edges, 4 corners, and clean controls when floating is true', () => {
    const html = renderToStaticMarkup(
      React.createElement(ScreenShareView, { stream: null, floating: true }),
    );
    expect(html).toContain('data-testid="screen-share-view"');

    // Maximize button
    expect(html).toContain('title="Maximize (Phóng to hết cỡ)"');

    // 4 Edge resize handles
    expect(html).toContain('title="Resize Top"');
    expect(html).toContain('title="Resize Bottom"');
    expect(html).toContain('title="Resize Left"');
    expect(html).toContain('title="Resize Right"');

    // 4 Corner resize handles
    expect(html).toContain('title="Resize Top-Left"');
    expect(html).toContain('title="Resize Top-Right"');
    expect(html).toContain('title="Resize Bottom-Left"');
    expect(html).toContain('title="Resize Bottom-Right"');
  });
});
