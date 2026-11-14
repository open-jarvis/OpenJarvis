import { useCallback, useEffect, useRef, useState } from 'react';
import { ACCEPTED_FILES, attachmentApi, formatBytes, type Attachment } from './attachmentApi';

type Props = {
  open: boolean;
  onClose: () => void;
  /** Queue an attachment for the next message. */
  onAttach: (att: Attachment) => void;
  onLog: (text: string, level?: 'info' | 'ok' | 'warn' | 'err') => void;
};

const KIND_LABEL: Record<Attachment['kind'], string> = {
  text: 'TEXT',
  document: 'DOC',
  image: 'IMAGE',
};

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function statusText(a: Attachment): string {
  if (a.status === 'describing') return 'Analysing image…';
  if (a.status === 'failed') return a.error || 'Could not read';
  if (a.kind === 'image') return 'Described';
  const pages = a.pages ? ` · ${a.pages} ${a.name.toLowerCase().endsWith('.xlsx') ? 'sheet' : 'page'}${a.pages === 1 ? '' : 's'}` : '';
  return `${a.text_chars.toLocaleString()} chars${pages}`;
}

export function AttachmentsDeck({ open, onClose, onAttach, onLog }: Props) {
  const [items, setItems] = useState<Attachment[]>([]);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Attachment | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await attachmentApi.list());
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void refresh();
    // Poll while open so image descriptions appear when ready.
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [open, refresh]);

  // Load the preview (text, and the image itself) for the selected item.
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setImageUrl(null);
    if (!selected) return;
    void (async () => {
      try {
        const full = await attachmentApi.get(selected.id);
        if (!cancelled) setSelected((s) => (s && s.id === full.id ? { ...s, ...full } : s));
        if (full.kind === 'image') {
          url = await attachmentApi.fileUrl(full.id);
          if (!cancelled) setImageUrl(url);
        }
      } catch { /* preview is best-effort */ }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
    // Only reload when a different attachment is selected.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      const res = await attachmentApi.upload(Array.from(files), 'upload');
      res.errors.forEach((e) => onLog(`${e.name}: ${e.error}`, 'err'));
      res.attachments.forEach((a) => onLog(`Added to library: ${a.name}`, 'ok'));
      await refresh();
    } catch (e) {
      onLog(`Upload failed: ${e instanceof Error ? e.message : e}`, 'err');
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const act = async (a: Attachment, action: 'knowledge' | 'delete' | 'open') => {
    setBusyId(a.id);
    try {
      if (action === 'knowledge') {
        const r = await attachmentApi.saveToKnowledge(a.id);
        onLog(`Saved ${a.name} to knowledge (${r.chunks} sections)`, 'ok');
      } else if (action === 'delete') {
        await attachmentApi.remove(a.id);
        if (selected?.id === a.id) setSelected(null);
        onLog(`Deleted ${a.name}`, 'warn');
      } else {
        const url = await attachmentApi.fileUrl(a.id);
        window.open(url, '_blank', 'noopener,noreferrer');
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
      await refresh();
    } catch (e) {
      onLog(`${a.name}: ${e instanceof Error ? e.message : e}`, 'err');
    } finally {
      setBusyId(null);
    }
  };

  if (!open) return null;

  return (
    <div className="deck" role="dialog" aria-modal="true" aria-label="Attachments">
      <div className="deck__backdrop" onClick={onClose} />
      <div className="deck__panel">
        <header className="deck__head">
          <div>
            <h2>FILE VAULT</h2>
            <span>Everything you have attached · reuse it in chat, routines or the knowledge base</span>
          </div>
          <div className="att-head-actions">
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPTED_FILES}
              hidden
              onChange={(e) => void upload(e.target.files)}
            />
            <button type="button" className="hud-btn" disabled={uploading} onClick={() => fileInput.current?.click()}>
              {uploading ? 'UPLOADING…' : 'ADD FILES'}
            </button>
            <button type="button" className="hud-btn hud-btn--ghost" onClick={onClose}>CLOSE</button>
          </div>
        </header>

        {error && <p className="deck__error">Attachment service: {error}</p>}

        <div className="deck__grid">
          <section className="deck__card deck__list">
            <h3>Library <small>{items.length}</small></h3>
            {items.length === 0 && (
              <p className="hud-muted">
                Nothing attached yet. Drop files on the HUD, paste an image, use the paperclip, or capture your screen.
              </p>
            )}
            {items.map((a) => (
              <article
                key={a.id}
                className={`deck-item att-item ${selected?.id === a.id ? 'is-selected' : ''} ${a.status === 'failed' ? 'is-paused' : ''}`}
              >
                <div className="deck-item__top">
                  <button
                    type="button"
                    className="deck-item__name"
                    onClick={() => setSelected(selected?.id === a.id ? null : a)}
                    aria-expanded={selected?.id === a.id}
                  >
                    {a.name}
                  </button>
                  <span className={`att-kind att-kind--${a.kind}`}>{KIND_LABEL[a.kind]}</span>
                </div>
                <div className="deck-item__meta">
                  <span>{fmtDate(a.created_at)} · {formatBytes(a.size)}{a.source === 'screenshot' ? ' · screenshot' : ''}</span>
                  <span className={a.status === 'failed' ? 'att-err' : ''}>
                    {statusText(a)}{a.knowledge_doc_id ? ' · in knowledge' : ''}
                  </span>
                </div>
                <div className="deck-item__actions">
                  <button type="button" disabled={busyId === a.id} onClick={() => { onAttach(a); onLog(`Attached ${a.name} to your next message`, 'ok'); }}>
                    ATTACH
                  </button>
                  <button type="button" disabled={busyId === a.id} onClick={() => act(a, 'open')}>OPEN</button>
                  <button
                    type="button"
                    disabled={busyId === a.id || !!a.knowledge_doc_id || a.status !== 'ready'}
                    onClick={() => act(a, 'knowledge')}
                    title="Add to Jarvis's searchable knowledge base"
                  >
                    {a.knowledge_doc_id ? 'IN KNOWLEDGE' : 'SAVE TO KNOWLEDGE'}
                  </button>
                  <button type="button" className="danger" disabled={busyId === a.id} onClick={() => act(a, 'delete')}>DELETE</button>
                </div>
              </article>
            ))}
          </section>

          <section className="deck__card att-preview">
            <h3>Preview</h3>
            {!selected ? (
              <p className="hud-muted">Select a file to see what Jarvis reads from it.</p>
            ) : (
              <>
                <p className="att-preview__name">{selected.name}</p>
                {imageUrl && <img className="att-preview__img" src={imageUrl} alt={selected.name} />}
                <pre className="att-preview__text">
                  {selected.status === 'describing'
                    ? 'Jarvis is analysing this image…'
                    : selected.preview || selected.error || '(no readable text)'}
                </pre>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
