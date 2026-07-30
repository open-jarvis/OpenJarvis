import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import {
  cancelCanonicalTask,
  createMutationContext,
  pauseCanonicalTask,
} from '../../lib/api';
import { useJarvisStore } from '../../lib/jarvisStore';

const TERMINAL = new Set(['done', 'failed', 'canceled']);

export function DesktopCloseGuard() {
  const [requested, setRequested] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);
  const activeTaskId = useJarvisStore((state) => state.activeTaskId);
  const tasks = useJarvisStore((state) => state.tasks);
  const upsertTask = useJarvisStore((state) => state.upsertTask);
  const setError = useJarvisStore((state) => state.setError);
  const activeTask = tasks.find((task) => task.task_id === activeTaskId) ?? null;

  useEffect(() => {
    if (typeof window === 'undefined' || !('__TAURI_INTERNALS__' in window)) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void import('@tauri-apps/api/window').then(async ({ getCurrentWindow }) => {
      const release = await getCurrentWindow().onCloseRequested((event) => {
        event.preventDefault();
        setRequested(true);
      });
      if (disposed) release();
      else unlisten = release;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (requested) primaryRef.current?.focus();
  }, [requested]);

  const finish = async (choice: 'background' | 'pause' | 'cancel') => {
    try {
      if (choice === 'pause' && activeTask?.status === 'running') {
        upsertTask(await pauseCanonicalTask(
          activeTask.task_id,
          createMutationContext('desktop-close-pause'),
        ));
      }
      if (choice === 'cancel' && activeTask && !TERMINAL.has(activeTask.status)) {
        upsertTask(await cancelCanonicalTask(
          activeTask.task_id,
          createMutationContext('desktop-close-cancel'),
        ));
      }
      setRequested(false);
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().hide();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Desktop close action failed.');
      primaryRef.current?.focus();
    }
  };

  const trapFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      setRequested(false);
      return;
    }
    if (event.key !== 'Tab' || !dialogRef.current) return;
    const buttons = [...dialogRef.current.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
    if (buttons.length === 0) return;
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.shiftKey
      ? (current <= 0 ? buttons.length - 1 : current - 1)
      : (current === buttons.length - 1 ? 0 : current + 1);
    event.preventDefault();
    buttons[next].focus();
  };

  if (!requested) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,0.65)' }}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="desktop-close-title"
        aria-describedby="desktop-close-description"
        onKeyDown={trapFocus}
        className="hud-panel w-full max-w-lg p-5"
      >
        <h2 id="desktop-close-title" className="text-lg font-semibold">Close OpenJarvis</h2>
        <p id="desktop-close-description" className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Choose what happens to the active task. No task is silently canceled.
        </p>
        <div className="mt-5 grid gap-3">
          <button ref={primaryRef} type="button" onClick={() => void finish('background')} className="rounded-lg px-4 py-3 text-left font-semibold" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
            Continue in background
          </button>
          <button type="button" disabled={activeTask?.status !== 'running'} onClick={() => void finish('pause')} className="rounded-lg px-4 py-3 text-left disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
            Pause active task, then hide
          </button>
          <button type="button" disabled={!activeTask || TERMINAL.has(activeTask.status)} onClick={() => void finish('cancel')} className="rounded-lg px-4 py-3 text-left disabled:opacity-40" style={{ border: '2px solid var(--color-error)', color: 'var(--color-error)' }}>
            Cancel active task, then hide
          </button>
          <button type="button" onClick={() => setRequested(false)} className="rounded-lg px-4 py-2 text-sm" style={{ border: '1px solid var(--color-border)' }}>
            Keep window open
          </button>
        </div>
      </div>
    </div>
  );
}
