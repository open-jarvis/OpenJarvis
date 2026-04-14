import React, { useState, useEffect, useCallback, useRef } from 'react';

type UpdateState = 'idle' | 'available' | 'downloading' | 'ready' | 'error';

const CHECK_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes

export function UpdateChecker() {
  const [state, setState] = useState<UpdateState>('idle');
  const [version, setVersion] = useState('');
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const [dismissed, setDismissed] = useState(false);
  const updateRef = useRef<any>(null);

  const checkForUpdate = useCallback(async () => {
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      if (update) {
        updateRef.current = update;
        setVersion(update.version);
        setState('available');
        setDismissed(false);
      }
    } catch {
      // Silently ignore — likely running in browser or no update available
    }
  }, []);

  useEffect(() => {
    // Check if we're in a Tauri environment
    if (typeof window === 'undefined' || !(window as any).__TAURI_INTERNALS__) {
      return;
    }

    checkForUpdate();
    const interval = setInterval(checkForUpdate, CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [checkForUpdate]);

  const handleDownload = useCallback(async () => {
    const update = updateRef.current;
    if (!update) return;

    setState('downloading');
    setProgress(0);

    try {
      let downloaded = 0;
      const contentLength = update.contentLength ?? 0;

      await update.downloadAndInstall((event: any) => {
        if (event.event === 'Started' && event.data?.contentLength) {
          // Content length received
        } else if (event.event === 'Progress') {
          downloaded += event.data?.chunkLength ?? 0;
          if (contentLength > 0) {
            setProgress(Math.min(100, Math.round((downloaded / contentLength) * 100)));
          }
        } else if (event.event === 'Finished') {
          setProgress(100);
        }
      });

      setState('ready');
    } catch (e: any) {
      setErrorMsg(e?.message || 'Download failed');
      setState('error');
      setTimeout(() => setState('idle'), 5000);
    }
  }, []);

  const handleRelaunch = useCallback(async () => {
    try {
      const { relaunch } = await import('@tauri-apps/plugin-process');
      await relaunch();
    } catch {
      // Fallback: inform user to restart manually
      setErrorMsg('Please restart the application manually');
      setState('error');
      setTimeout(() => setState('idle'), 5000);
    }
  }, []);

  if (state === 'idle' || dismissed) return null;

  return (
    <div style={styles.banner}>
      {state === 'available' && (
        <div style={styles.row}>
          <span>Update available: <strong>v{version}</strong></span>
          <div style={styles.actions}>
            <button style={styles.primaryBtn} onClick={handleDownload}>Download</button>
            <button style={styles.secondaryBtn} onClick={() => setDismissed(true)}>Dismiss</button>
          </div>
        </div>
      )}

      {state === 'downloading' && (
        <div style={styles.row}>
          <span>Downloading update... {progress}%</span>
          <div style={styles.progressBar}>
            <div style={{ ...styles.progressFill, width: `${progress}%` }} />
          </div>
        </div>
      )}

      {state === 'ready' && (
        <div style={styles.row}>
          <span style={{ color: '#a6e3a1' }}>Update installed.</span>
          <div style={styles.actions}>
            <button style={styles.successBtn} onClick={handleRelaunch}>Relaunch now</button>
            <button style={styles.secondaryBtn} onClick={() => setDismissed(true)}>Later</button>
          </div>
        </div>
      )}

      {state === 'error' && (
        <div style={styles.row}>
          <span style={{ color: '#f38ba8' }}>Update error: {errorMsg}</span>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  banner: {
    padding: '10px 24px',
    backgroundColor: '#181825',
    borderBottom: '1px solid #313244',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '16px',
    fontSize: '13px',
  },
  actions: {
    display: 'flex',
    gap: '8px',
  },
  primaryBtn: {
    padding: '4px 14px',
    border: 'none',
    borderRadius: '4px',
    backgroundColor: '#89b4fa',
    color: '#1e1e2e',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  successBtn: {
    padding: '4px 14px',
    border: 'none',
    borderRadius: '4px',
    backgroundColor: '#a6e3a1',
    color: '#1e1e2e',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  secondaryBtn: {
    padding: '4px 14px',
    border: '1px solid #45475a',
    borderRadius: '4px',
    backgroundColor: 'transparent',
    color: '#a6adc8',
    fontSize: '12px',
    cursor: 'pointer',
  },
  progressBar: {
    flex: 1,
    maxWidth: '300px',
    height: '6px',
    backgroundColor: '#313244',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#89b4fa',
    borderRadius: '3px',
    transition: 'width 0.3s ease',
  },
};
