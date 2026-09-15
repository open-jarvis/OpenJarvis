import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createKioskPresentationLifecycle,
  ensurePresentationSession,
  shouldEnsurePresentationSession,
  resetPresentationSession,
} from './kioskPresentation';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('kiosk presentation API', () => {
  it('re-ensures presentation while a customer is approaching or being served', () => {
    expect(shouldEnsurePresentationSession('idle')).toBe(false);
    expect(shouldEnsurePresentationSession('cleanup')).toBe(false);
    expect(shouldEnsurePresentationSession('approaching')).toBe(true);
    expect(shouldEnsurePresentationSession('prompting')).toBe(true);
    expect(shouldEnsurePresentationSession('active')).toBe(true);
  });

  it('ensures a presentation session for the current frontend origin', async () => {
    vi.stubGlobal('window', { location: { origin: 'http://127.0.0.1:5173' } });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ presentation_session_id: 'session-1' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(ensurePresentationSession(window.location.origin))
      .resolves.toBe('session-1');
    expect(fetchMock).toHaveBeenCalledWith('/api/kiosk/presentation/ensure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_origin: window.location.origin }),
    });
  });

  it('resets the encoded presentation session path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    await resetPresentationSession('customer/session 1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/kiosk/presentation/customer%2Fsession%201/reset',
      { method: 'POST', headers: {} },
    );
  });

  it('correlates a reset with the active voice generation', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    await resetPresentationSession('session-1', 'thread-1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/kiosk/presentation/session-1/reset',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ generation: 'thread-1' }),
      },
    );
  });

  it('raises concise errors for non-OK responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));

    await expect(ensurePresentationSession('http://127.0.0.1:5173'))
      .rejects.toThrow('Unable to start customer display');
    await expect(resetPresentationSession('session-1'))
      .rejects.toThrow('Unable to reset customer display');
  });

  it('retries a transient presentation failure until the display session is ready', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ presentation_session_id: 'recovered-session' }),
      });
    vi.stubGlobal('fetch', fetchMock);

    const session = ensurePresentationSession('http://127.0.0.1:5173');
    const recovered = expect(session).resolves.toBe('recovered-session');
    await vi.advanceTimersByTimeAsync(500);

    await recovered;
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('kiosk presentation lifecycle', () => {
  it('does not reset a preloaded display before the first voice turn', () => {
    const reset = vi.fn().mockResolvedValue(undefined);
    const lifecycle = createKioskPresentationLifecycle(reset);

    lifecycle.requestReset();
    lifecycle.setSessionId('session-1');
    expect(reset).not.toHaveBeenCalled();

    lifecycle.markActive('thread-1');
    lifecycle.requestReset();
    expect(reset).toHaveBeenCalledOnce();
    expect(reset).toHaveBeenLastCalledWith('session-1', 'thread-1');
  });

  it('waits for voice teardown before requesting presentation reset', async () => {
    let finishVoiceEnd: (() => void) | undefined;
    const endVoice = vi.fn(() => new Promise<void>((resolve) => {
      finishVoiceEnd = resolve;
    }));
    const reset = vi.fn().mockResolvedValue(undefined);
    const lifecycle = createKioskPresentationLifecycle(reset);
    lifecycle.setSessionId('session-1');
    lifecycle.markActive('thread-1');

    const teardown = lifecycle.endVoiceThenReset(endVoice);
    const duplicateTeardown = lifecycle.endVoiceThenReset(endVoice);
    expect(endVoice).toHaveBeenCalledOnce();
    expect(reset).not.toHaveBeenCalled();

    finishVoiceEnd?.();
    await Promise.all([teardown, duplicateTeardown]);
    expect(reset).toHaveBeenCalledOnce();
  });

  it('drops a pre-ensure reset when a new voice generation becomes active', () => {
    const reset = vi.fn().mockResolvedValue(undefined);
    const lifecycle = createKioskPresentationLifecycle(reset);

    lifecycle.requestReset();
    lifecycle.markActive('thread-1');
    lifecycle.setSessionId('session-1');

    expect(reset).not.toHaveBeenCalled();
  });
});
