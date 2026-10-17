import { isTauri } from './api';

let pending: Promise<unknown> = Promise.resolve();
function update(busy: boolean): Promise<void> {
  const request = pending.catch(() => {}).then(async () => {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('set_desktop_speech_busy', { busy });
  });
  pending = request;
  return request;
}

/** Wait for the local wake microphone to close before response playback. */
export async function suspendDesktopWake(): Promise<void> {
  if (!isTauri()) return;
  await update(true);
}

export function resumeDesktopWake(): void {
  if (!isTauri()) return;
  void update(false)
    .catch(() => { /* A disconnected desktop stays conservatively suspended. */ });
}
