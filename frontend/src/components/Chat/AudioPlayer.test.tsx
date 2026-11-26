import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
}));

vi.mock('../../lib/api', () => ({
  apiFetch: mocks.apiFetch,
}));

import { AudioPlayer } from './AudioPlayer';

describe('AudioPlayer', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders audio player container and controls for relative src', () => {
    const html = renderToStaticMarkup(<AudioPlayer src="/api/digest/audio" />);

    expect(html).toContain('Morning Digest');
    expect(html).toContain('0:00');
    expect(html).toContain('--:--');
    expect(html).toContain('button');
  });

  it('renders audio element immediately when given a blob URL', () => {
    const html = renderToStaticMarkup(<AudioPlayer src="blob:http://localhost/fake-audio" />);

    expect(html).toContain('src="blob:http://localhost/fake-audio"');
    expect(html).toContain('Morning Digest');
  });

  it('renders audio element immediately when given a data URL', () => {
    const html = renderToStaticMarkup(<AudioPlayer src="data:audio/mp3;base64,AAAA" />);

    expect(html).toContain('src="data:audio/mp3;base64,AAAA"');
    expect(html).toContain('Morning Digest');
  });
});
