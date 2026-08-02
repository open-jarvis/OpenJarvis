import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchLocalVoices,
  fetchVoiceAudition,
  generateVoiceAuditions,
  selectLocalVoice,
} from '../../lib/api';
import type { LocalVoiceStatus, VoiceProfileInfo } from '../../lib/api';

interface VoiceProfileCardProps {
  profile: VoiceProfileInfo;
  audioUrl?: string;
  selected: boolean;
  busy: boolean;
  onSelect: (voiceId: string) => void;
}

export function VoiceProfileCard({
  profile,
  audioUrl,
  selected,
  busy,
  onSelect,
}: VoiceProfileCardProps) {
  return (
    <article
      className="rounded-xl p-4"
      style={{ border: selected ? '2px solid var(--color-accent)' : '1px solid var(--color-border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{profile.number}. {profile.label}</h3>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{profile.description}</p>
        </div>
        <span className="rounded-full px-2 py-1 text-xs" style={{ background: 'var(--color-bg-tertiary)' }}>
          {profile.backend}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-[7rem_1fr] gap-x-2 gap-y-1 text-xs">
        <dt>Tonhöhe</dt><dd>{profile.pitch_semitones} Halbtöne</dd>
        <dt>Tempo</dt><dd>{profile.speed.toFixed(2)}×</dd>
        <dt>Emotion</dt><dd>{profile.backend === 'chatterbox' ? profile.exaggeration.toFixed(2) : 'kontrolliert'}</dd>
        <dt>CFG</dt><dd>{profile.backend === 'chatterbox' ? profile.cfg_weight.toFixed(2) : 'n/a'}</dd>
        <dt>Seed</dt><dd>{profile.backend === 'chatterbox' ? profile.seed : 'deterministisch'}</dd>
      </dl>
      {audioUrl ? (
        <audio className="mt-3 w-full" controls preload="metadata" src={audioUrl}>
          Diese WebView unterstützt keine WAV-Wiedergabe.
        </audio>
      ) : (
        <p className="mt-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>Probe wurde noch nicht erzeugt.</p>
      )}
      <button
        type="button"
        aria-pressed={selected}
        disabled={busy || selected}
        onClick={() => onSelect(profile.voice_id)}
        className="mt-3 rounded-lg px-3 py-2 text-sm disabled:opacity-50 focus-visible:outline-2"
        style={{ border: '1px solid var(--color-border)' }}
      >
        {selected ? 'Als JARVIS-Stimme ausgewählt' : 'Als JARVIS-Stimme verwenden'}
      </button>
    </article>
  );
}

export function VoiceAuditionPanel({ embedded = false }: { embedded?: boolean }) {
  const [status, setStatus] = useState<LocalVoiceStatus | null>(null);
  const [audioUrls, setAudioUrls] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const urlsRef = useRef<Record<string, string>>({});

  const replaceUrls = useCallback((next: Record<string, string>) => {
    Object.values(urlsRef.current).forEach((url) => URL.revokeObjectURL(url));
    urlsRef.current = next;
    setAudioUrls(next);
  }, []);

  const refresh = useCallback(async () => {
    const nextStatus = await fetchLocalVoices();
    setStatus(nextStatus);
    const ready = nextStatus.profiles.filter((profile) => profile.audition_ready);
    const entries = await Promise.all(ready.map(async (profile) => {
      const blob = await fetchVoiceAudition(profile.voice_id);
      return [profile.voice_id, URL.createObjectURL(blob)] as const;
    }));
    replaceUrls(Object.fromEntries(entries));
  }, [replaceUrls]);

  useEffect(() => {
    void refresh().catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Sprachdienst ist nicht verfügbar.');
    });
    return () => Object.values(urlsRef.current).forEach((url) => URL.revokeObjectURL(url));
  }, [refresh]);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      await generateVoiceAuditions();
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Sprachproben konnten nicht erzeugt werden.');
    } finally {
      setBusy(false);
    }
  };

  const select = async (voiceId: string) => {
    setBusy(true);
    setError(null);
    try {
      await selectLocalVoice(voiceId);
      setStatus((current) => current ? { ...current, selected_voice_id: voiceId } : current);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Stimme konnte nicht ausgewählt werden.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className={embedded ? 'mt-4 rounded-xl p-3' : 'hud-panel p-4'}
      style={embedded ? { border: '1px solid var(--color-border)' } : undefined}
      aria-labelledby="voice-audition-heading"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="voice-audition-heading" className="font-semibold">Stimmenauswahl</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Chatterbox Multilingual V3 · Piper-CPU-Fallback · Deutsch · keine Referenzstimme
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void generate()}
          className="rounded-lg px-3 py-2 text-sm disabled:opacity-40 focus-visible:outline-2"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          {busy ? 'Wird erzeugt…' : 'Alle Proben erzeugen'}
        </button>
      </div>

      {error && <p role="alert" className="mt-3 text-sm" style={{ color: 'var(--color-error)' }}>{error}</p>}
      {busy && (
        <p role="status" className="mt-3 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Lokale Erzeugung läuft. Der erste Chatterbox-Lauf kann mehrere Minuten dauern; diese Ansicht bleibt bedienbar.
        </p>
      )}
      {!status && !error && <p className="mt-4 text-sm">Lokaler Sprachdienst wird geladen…</p>}
      {status && (
        <>
          <div className="mt-4 rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
            <strong>Fester Vergleichstext</strong>
            <p className="mt-1" lang="de">„{status.audition_text}“</p>
            <p className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              Worker: {status.worker.device} · CUDA {status.worker.cuda ? 'bereit' : 'nicht verfügbar'} · Fallback {status.fallback_backend}
            </p>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              Modelle: Chatterbox {status.worker.chatterbox_loaded ? 'vorgewärmt' : 'lädt bei erster Nutzung'} · Piper {status.worker.piper_loaded ? 'vorgewärmt' : 'lädt bei erster Nutzung'}
            </p>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {status.profiles.map((profile) => {
              const selected = status.selected_voice_id === profile.voice_id;
              return (
                <VoiceProfileCard
                  key={profile.voice_id}
                  profile={profile}
                  audioUrl={audioUrls[profile.voice_id]}
                  selected={selected}
                  busy={busy}
                  onSelect={(voiceId) => void select(voiceId)}
                />
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
