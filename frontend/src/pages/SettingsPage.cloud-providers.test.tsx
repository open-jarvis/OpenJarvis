import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

describe('desktop cloud provider settings', () => {
  it('offers Atlas Cloud key storage alongside its provider status', async () => {
    vi.stubGlobal('localStorage', { getItem: () => null });
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} });
    const { SettingsPage } = await import('./SettingsPage');
    const html = renderToStaticMarkup(<SettingsPage />);

    expect(html).toContain('Atlas Cloud');
    const atlasKeyInput = html.match(/<input[^>]*placeholder="Atlas Cloud API key"[^>]*>/)?.[0];
    expect(atlasKeyInput).toBeDefined();
    expect(atlasKeyInput).not.toContain('disabled');

    expect(html).toContain('Cheaper Inference');
    const cheaperKeyInput = html.match(/<input[^>]*placeholder="ci_live_\.\.\."[^>]*>/)?.[0];
    expect(cheaperKeyInput).toBeDefined();
    expect(cheaperKeyInput).not.toContain('disabled');
    vi.unstubAllGlobals();
  });
});
