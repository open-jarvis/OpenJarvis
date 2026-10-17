import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ native: vi.fn(), invoke: vi.fn() }));
vi.mock('./api', () => ({ isTauri: mocks.native }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));

beforeEach(() => { vi.resetModules(); mocks.native.mockReturnValue(true); mocks.invoke.mockReset(); });
afterEach(() => { vi.clearAllMocks(); });

it('does not invoke native permissions from the browser', async () => {
  mocks.native.mockReturnValue(false);
  const wake = await import('./desktop-wake');
  await wake.suspendDesktopWake();
  wake.resumeDesktopWake();
  expect(mocks.invoke).not.toHaveBeenCalled();
});

it('waits for wake suspension and serializes resume after it', async () => {
  let finish!: () => void;
  mocks.invoke.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
  const wake = await import('./desktop-wake');
  const suspended = wake.suspendDesktopWake();
  wake.resumeDesktopWake();
  await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledTimes(1));
  expect(mocks.invoke).toHaveBeenCalledWith('set_desktop_speech_busy', { busy: true });
  finish();
  await suspended;
  await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledTimes(2));
  expect(mocks.invoke).toHaveBeenLastCalledWith('set_desktop_speech_busy', { busy: false });
});

it('rejects playback readiness when wake suspension fails', async () => {
  mocks.invoke.mockRejectedValueOnce(new Error('unavailable'));
  const wake = await import('./desktop-wake');
  await expect(wake.suspendDesktopWake()).rejects.toThrow('unavailable');
});
