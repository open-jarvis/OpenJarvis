import { apiFetch } from '../../lib/api';

export interface Attachment {
  id: string;
  name: string;
  mime: string;
  size: number;
  kind: 'text' | 'document' | 'image';
  source: string;
  created_at: string;
  pages: number | null;
  text_chars: number;
  status: 'ready' | 'describing' | 'failed';
  error: string;
  knowledge_doc_id: string | null;
  preview?: string;
}

export const ACCEPTED_FILES =
  '.txt,.md,.csv,.tsv,.json,.log,.xml,.html,.css,.js,.jsx,.ts,.tsx,.py,.java,.c,.cpp,.cs,.go,.rs,.rb,.php,.sh,.ps1,.sql,.yaml,.yml,.toml,.ini,.pdf,.docx,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.bmp';

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const attachmentApi = {
  async upload(files: File[], source: 'upload' | 'paste' | 'drop' | 'screenshot' = 'upload') {
    const form = new FormData();
    for (const f of files) form.append('files', f, f.name);
    form.append('source', source);
    return json<{ attachments: Attachment[]; errors: { name: string; error: string }[] }>(
      await apiFetch('/v1/attachments', { method: 'POST', body: form }),
    );
  },
  list: async (): Promise<Attachment[]> =>
    (await json<{ attachments: Attachment[] }>(await apiFetch('/v1/attachments'))).attachments,
  get: async (id: string): Promise<Attachment> => json<Attachment>(await apiFetch(`/v1/attachments/${id}`)),
  remove: async (id: string) => json(await apiFetch(`/v1/attachments/${id}`, { method: 'DELETE' })),
  saveToKnowledge: async (id: string) =>
    json<{ chunks: number }>(await apiFetch(`/v1/attachments/${id}/knowledge`, { method: 'POST' })),
  /** Object URL for previewing/opening the original file (revoke when done). */
  async fileUrl(id: string): Promise<string> {
    const res = await apiFetch(`/v1/attachments/${id}/file`);
    if (!res.ok) throw new Error(`${res.status}`);
    return URL.createObjectURL(await res.blob());
  },
};

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Capture the screen (or one window/tab the user picks) as a PNG file.
 * Uses the browser's screen-share picker, so the user chooses what is shared
 * every time; nothing is captured without that confirmation.
 */
export async function captureScreenshot(): Promise<File> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error('Screen capture is not supported in this browser.');
  }
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  try {
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    // Let the first real frame arrive.
    await new Promise((r) => setTimeout(r, 300));
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')!.drawImage(video, 0, 0);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/png'));
    if (!blob) throw new Error('Could not capture the screen.');
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    return new File([blob], `screenshot-${stamp}.png`, { type: 'image/png' });
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}
