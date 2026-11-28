import { describe, expect, it, vi } from 'vitest';

vi.mock('../../lib/store', () => ({ useAppStore: vi.fn() }));

import { downloadThenInstallUpdate } from './UpdateChecker';

function fakeUpdate(calls: string[], installError?: Error) {
  return {
    download: vi.fn(async () => { calls.push('download'); }),
    install: vi.fn(async () => {
      calls.push('install');
      if (installError) throw installError;
    }),
  };
}

describe('desktop update install', () => {
  it('stops app-owned services after downloading and before installing', async () => {
    const calls: string[] = [];
    const prepare = vi.fn(async () => { calls.push('prepare'); return true; });
    const restart = vi.fn(async () => {});

    await downloadThenInstallUpdate(fakeUpdate(calls), () => {}, prepare, restart);

    expect(calls).toEqual(['download', 'prepare', 'install']);
    expect(restart).not.toHaveBeenCalled();
  });

  it('keeps services running when the download fails', async () => {
    const prepare = vi.fn(async () => true);
    const update = {
      download: vi.fn(async () => { throw new Error('offline'); }),
      install: vi.fn(async () => {}),
    };

    await expect(downloadThenInstallUpdate(update, () => {}, prepare)).rejects.toThrow('offline');
    expect(prepare).not.toHaveBeenCalled();
    expect(update.install).not.toHaveBeenCalled();
  });

  it('restarts stopped services when installing fails', async () => {
    const calls: string[] = [];
    const restart = vi.fn(async () => {});

    await expect(
      downloadThenInstallUpdate(fakeUpdate(calls, new Error('installer')), () => {}, async () => true, restart),
    ).rejects.toThrow('installer');
    expect(restart).toHaveBeenCalledOnce();
  });
});
