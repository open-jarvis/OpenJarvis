import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('./api', () => ({ apiFetch: mocks.apiFetch }));
import { loadAudioSource } from './authenticated-audio';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

describe('authenticated audio source lifecycle', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset();
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:owned-audio');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it('loads through the authenticated API and releases its own blob once', async () => {
    mocks.apiFetch.mockResolvedValue(new Response(new Blob(['audio'])));
    const ready = vi.fn(); const error = vi.fn();
    const dispose = loadAudioSource('/api/digest/audio', ready, error);
    await vi.waitFor(() => expect(ready).toHaveBeenCalledWith('blob:owned-audio'));
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/digest/audio', { signal: expect.any(AbortSignal) });
    expect(error).not.toHaveBeenCalled();
    dispose(); dispose();
    expect(mocks.apiFetch.mock.calls[0][1].signal.aborted).toBe(true);
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:owned-audio');
  });

  it.each(['blob:http://localhost/caller-owned', 'data:audio/mp3;base64,AAAA'])(
    'preserves caller-owned URLs without fetching or revoking: %s', (url) => {
      const ready = vi.fn(); const dispose = loadAudioSource(url, ready, vi.fn());
      expect(ready).toHaveBeenCalledWith(url);
      dispose();
      expect(mocks.apiFetch).not.toHaveBeenCalled();
      expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    },
  );

  it('discards a late network response after disposal', async () => {
    const response = deferred<Response>(); mocks.apiFetch.mockReturnValue(response.promise);
    const ready = vi.fn(); const error = vi.fn();
    const dispose = loadAudioSource('/api/digest/audio', ready, error);
    dispose(); response.resolve(new Response(new Blob(['stale'])));
    await response.promise; await new Promise((resolve) => setTimeout(resolve, 0));
    expect(ready).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('discards a blob that finishes reading after disposal', async () => {
    const body = deferred<Blob>();
    mocks.apiFetch.mockResolvedValue({ ok: true, blob: () => body.promise });
    const ready = vi.fn(); const dispose = loadAudioSource('/api/digest/audio', ready, vi.fn());
    await Promise.resolve(); dispose(); body.resolve(new Blob(['stale']));
    await body.promise; await new Promise((resolve) => setTimeout(resolve, 0));
    expect(ready).not.toHaveBeenCalled(); expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('reports HTTP failures without creating a playable URL', async () => {
    mocks.apiFetch.mockResolvedValue(new Response(null, { status: 401 }));
    const ready = vi.fn(); const error = vi.fn();
    const dispose = loadAudioSource('/api/digest/audio', ready, error);
    await vi.waitFor(() => expect(error).toHaveBeenCalledWith('Failed to load audio (401)'));
    expect(ready).not.toHaveBeenCalled(); expect(URL.createObjectURL).not.toHaveBeenCalled(); dispose();
  });

  it('reports a rejected destination and suppresses cancellation errors', async () => {
    mocks.apiFetch.mockRejectedValue(new Error('API request must stay on the configured server'));
    const error = vi.fn(); const dispose = loadAudioSource('https://other.example/audio', vi.fn(), error);
    await vi.waitFor(() => expect(error).toHaveBeenCalledWith('API request must stay on the configured server'));
    dispose();
    mocks.apiFetch.mockImplementation((_src, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')));
    }));
    const cancelledError = vi.fn(); const cancel = loadAudioSource('/api/digest/audio', vi.fn(), cancelledError);
    cancel(); await Promise.resolve(); await Promise.resolve(); expect(cancelledError).not.toHaveBeenCalled();
  });
});
