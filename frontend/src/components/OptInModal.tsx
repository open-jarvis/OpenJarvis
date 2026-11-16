import { useEffect, useRef, useState } from 'react';
import { Trophy, X } from 'lucide-react';
import { useAppStore } from '../lib/store';
import { isProfane } from '../lib/profanity';
import { fetchAnalyticsIdentity, saveAnalyticsPreference } from '../lib/analytics';

interface OptInModalProps {
  onClose: () => void;
}

export function OptInModal({ onClose }: OptInModalProps) {
  const setOptIn = useAppStore((s) => s.setOptIn);
  const optInDisplayName = useAppStore((s) => s.optInDisplayName);
  const optInEmail = useAppStore((s) => s.optInEmail);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const [name, setName] = useState(optInDisplayName);
  const [email, setEmail] = useState(optInEmail);
  const [joined, setJoined] = useState(optInEnabled);
  const [analyticsEnabled, setAnalyticsEnabled] = useState(false);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    fetchAnalyticsIdentity()
      .then((identity) => { if (active) setAnalyticsEnabled(identity.enabled); })
      .catch(() => {
        if (active) setError('Could not load analytics. You can retry saving your choice.');
      })
      .finally(() => { if (active) setAnalyticsLoading(false); });
    return () => { active = false; };
  }, []);

  const handleJoin = async (enableAnalytics: boolean) => {
    if (saving || analyticsLoading) return;
    const trimmed = name.trim();
    const trimmedEmail = email.trim();
    if (trimmed.length < 2 || trimmed.length > 30) {
      setError('Please enter a display name with 2–30 characters.');
      return;
    }
    if (isProfane(trimmed)) {
      setError('Please choose a different name.');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError('Please enter a valid email address.');
      return;
    }
    setError('');
    setSaving(true);
    try {
      await saveAnalyticsPreference(enableAnalytics);
      setAnalyticsEnabled(enableAnalytics);
      setOptIn(true, trimmed, trimmedEmail);
      setJoined(true);
      setStatus(enableAnalytics ? 'Usage analytics enabled.' : 'Usage analytics are off.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save your sharing choice.');
    } finally {
      setSaving(false);
    }
  };

  const handleAnalytics = async (enabled: boolean, close: boolean) => {
    if (saving || analyticsLoading) return;
    setError('');
    setSaving(true);
    try {
      await saveAnalyticsPreference(enabled);
      setAnalyticsEnabled(enabled);
      setStatus(enabled ? 'Usage analytics enabled.' : 'Usage analytics are off.');
      if (close) onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save your analytics choice.');
    } finally {
      setSaving(false);
    }
  };

  const busy = saving || analyticsLoading;
  const primaryStyle = {
    background: 'var(--color-accent)',
    color: 'var(--color-on-accent)',
  };
  const inputStyle = {
    background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text)',
  };
  const buttonClass = 'min-h-10 rounded-xl px-3 py-2 text-sm font-medium cursor-pointer disabled:opacity-50';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backdropFilter: 'blur(8px)', background: 'rgba(0,0,0,0.4)' }}
      onClick={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sharing-modal-title"
        className="relative w-full max-w-md mx-4 max-h-[90dvh] overflow-y-auto rounded-2xl p-4 sm:p-6"
        style={{
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          boxShadow: '0 24px 80px rgba(0,0,0,0.25)',
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !saving) onClose();
          if (event.key !== 'Tab') return;
          const controls = dialogRef.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]), input:not([disabled]), a[href]',
          );
          if (!controls?.length) return;
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <button
          type="button"
          aria-label="Close sharing choices"
          onClick={onClose}
          disabled={saving}
          className="absolute right-3 top-3 p-1.5 rounded-lg cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
        ><X size={16} /></button>

        <div className="flex items-center gap-3 pr-6 mb-2">
          <div
            className="flex items-center justify-center w-9 h-9 rounded-xl shrink-0"
            style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
          ><Trophy size={20} /></div>
          <h2 id="sharing-modal-title" className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
            Win a Mac mini
          </h2>
        </div>
        <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--color-text-secondary)' }}>
          Share your savings on the leaderboard for a chance to win a Mac mini.
        </p>

        {error && <p role="alert" className="text-xs mb-3" style={{ color: 'var(--color-error)' }}>{error}</p>}
        {status && <p role="status" className="text-xs mb-3" style={{ color: 'var(--color-text-secondary)' }}>{status}</p>}

        {!joined && (
          <form
            id="sharing-entry-form"
            onSubmit={(event) => { event.preventDefault(); void handleJoin(false); }}
            className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3"
          >
            <div>
              <label htmlFor="sharing-display-name" className="block text-xs mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                Display name (public)
              </label>
              <input
                id="sharing-display-name"
                type="text"
                value={name}
                disabled={saving}
                maxLength={30}
                onChange={(event) => { setName(event.target.value); setError(''); }}
                placeholder="Your leaderboard name"
                className="w-full rounded-lg px-3 py-2 text-base sm:text-sm"
                style={inputStyle}
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="sharing-contact-email" className="block text-xs mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                Email (not displayed)
              </label>
              <input
                id="sharing-contact-email"
                type="email"
                value={email}
                disabled={saving}
                onChange={(event) => { setEmail(event.target.value); setError(''); }}
                placeholder="you@example.com"
                className="w-full rounded-lg px-3 py-2 text-base sm:text-sm"
                style={inputStyle}
              />
            </div>
          </form>
        )}

        <div className="text-xs leading-relaxed mb-3" style={{ color: 'var(--color-text-secondary)' }}>
          <p className="mb-1">
            Optional analytics sends usage counts, timings, errors, environment metadata,
            and a random ID to PostHog.
          </p>
          <p>
            Leaderboard entries send your name, email, and savings to Supabase.
            Your name and savings are public; email is not displayed.
          </p>
          <a
            href="https://open-jarvis.github.io/OpenJarvis/telemetry/"
            target="_blank"
            rel="noreferrer"
            className="inline-block underline mt-1"
          >Privacy details</a>
        </div>

        {joined ? (
          <div className="space-y-2">
            <p className="text-sm mb-3" style={{ color: 'var(--color-text)' }}>
              Leaderboard sharing enabled · Analytics {analyticsEnabled ? 'on' : 'off'}
            </p>
            <button
              type="button"
              onClick={() => void handleAnalytics(!analyticsEnabled, false)}
              disabled={busy}
              className={buttonClass + ' w-full'}
              style={primaryStyle}
            >{saving ? 'Saving…' : analyticsEnabled ? 'Disable analytics' : 'Enable analytics'}</button>
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={onClose} disabled={saving} className={buttonClass} style={{ color: 'var(--color-text)' }}>Done</button>
              <button
                type="button"
                onClick={() => { setOptIn(false, '', ''); setJoined(false); onClose(); }}
                disabled={saving}
                className={buttonClass}
                style={{ color: 'var(--color-text-secondary)' }}
              >Stop leaderboard updates</button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => void handleJoin(true)}
              disabled={busy}
              className={buttonClass + ' w-full'}
              style={primaryStyle}
            >{saving ? 'Saving…' : 'Enable analytics & enter giveaway'}</button>
            <div className="grid grid-cols-2 gap-2">
              <button type="submit" form="sharing-entry-form" disabled={busy} className={buttonClass} style={{ color: 'var(--color-text)' }}>
                Enter giveaway only
              </button>
              <button type="button" onClick={() => void handleAnalytics(true, true)} disabled={busy} className={buttonClass} style={{ color: 'var(--color-text)' }}>
                Enable analytics only
              </button>
            </div>
            <button
              type="button"
              onClick={() => void handleAnalytics(false, true)}
              disabled={busy}
              className={buttonClass + ' w-full border'}
              style={{ color: 'var(--color-text)', borderColor: 'var(--color-border)' }}
            >Continue without sharing</button>
          </div>
        )}
      </div>
    </div>
  );
}
