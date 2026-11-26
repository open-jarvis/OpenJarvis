import { apiFetch } from './api';

/** Load one audio source and return ownership-aware, idempotent cleanup. */
export function loadAudioSource(
  src: string,
  onReady: (url: string) => void,
  onError: (message: string) => void,
): () => void {
  // These URLs belong to the caller. Do not fetch or revoke them here.
  if (src.startsWith('blob:') || src.startsWith('data:')) {
    onReady(src);
    return () => {};
  }
  const controller = new AbortController();
  let active = true;
  let ownedUrl: string | null = null;
  apiFetch(src, { signal: controller.signal })
    .then(async (response) => {
      if (!response.ok) throw new Error(`Failed to load audio (${response.status})`);
      const blob = await response.blob();
      if (!active) return;
      ownedUrl = URL.createObjectURL(blob);
      onReady(ownedUrl);
    })
    .catch((error) => {
      if (active && !controller.signal.aborted) {
        onError(error instanceof Error ? error.message : 'Failed to load audio');
      }
    });
  return () => {
    if (!active) return;
    active = false;
    controller.abort();
    if (ownedUrl) URL.revokeObjectURL(ownedUrl);
  };
}
