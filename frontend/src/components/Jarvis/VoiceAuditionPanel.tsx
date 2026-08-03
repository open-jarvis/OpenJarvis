import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchLocalVoices,
  fetchElevenLabsVoices,
  fetchVoiceAudition,
  generateVoiceAuditions,
  selectLocalVoice,
  selectElevenLabsVoice,
  updateVoiceLimits,
} from '../../lib/api';
import type { ElevenLabsVoiceInfo, LocalVoiceStatus, VoiceProfileInfo } from '../../lib/api';

const BACKEND_LABELS: Record<string, string> = {
  elevenlabs: 'ElevenLabs',
  chatterbox: 'Chatterbox (GPU)',
  piper: 'Piper (CPU)',
};

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
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {profile.backend === 'piper'
              ? 'CPU-Notfallprofil für schnelle, kontrollierte Sprachausgabe.'
              : 'Ruhiges Stimmprofil, ein eigenes neuronales Timbre.'}
          </p>
        </div>
        <span className="rounded-full px-2 py-1 text-xs" style={{ background: 'var(--color-bg-tertiary)' }}>
          {BACKEND_LABELS[profile.backend] ?? profile.backend}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-[7rem_1fr] gap-x-2 gap-y-1 text-xs">
        <dt>Engine</dt><dd>{BACKEND_LABELS[profile.backend] ?? profile.backend}</dd>
        <dt>Tempo</dt><dd>{profile.speed.toFixed(2)}×</dd>
        <dt>Seed</dt><dd>{profile.backend === 'piper' ? 'n/a' : profile.seed}</dd>
        <dt>Ausdruck</dt><dd>{profile.backend === 'piper' ? 'n/a' : profile.exaggeration.toFixed(2)}</dd>
      </dl>
      {audioUrl ? (
        <>
          <p className="mt-3 text-xs" style={{ color: profile.audition_fallback_used ? 'var(--color-warning)' : 'var(--color-text-secondary)' }}>
            Probe: {BACKEND_LABELS[profile.audition_backend] ?? profile.audition_backend}
            {profile.audition_fallback_used ? ' · Fallback' : ''}
          </p>
          <audio className="mt-2 w-full" controls preload="metadata" src={audioUrl}>
            Diese WebView unterstützt die Audiowiedergabe nicht.
          </audio>
        </>
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
  const [elevenLabsVoices, setElevenLabsVoices] = useState<ElevenLabsVoiceInfo[]>([]);
  const [elevenLabsVoiceId, setElevenLabsVoiceId] = useState('');
  const [monthlyLimit, setMonthlyLimit] = useState('100000');
  const [responseLimit, setResponseLimit] = useState('4000');
  const urlsRef = useRef<Record<string, string>>({});

  const replaceUrls = useCallback((next: Record<string, string>) => {
    Object.values(urlsRef.current).forEach((url) => URL.revokeObjectURL(url));
    urlsRef.current = next;
    setAudioUrls(next);
  }, []);

  const refresh = useCallback(async () => {
    const nextStatus = await fetchLocalVoices();
    setStatus(nextStatus);
    setElevenLabsVoiceId(nextStatus.elevenlabs_voice_id || '');
    setMonthlyLimit(String(nextStatus.monthly_char_limit));
    setResponseLimit(String(nextStatus.per_response_char_limit));
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

  const usage = status?.worker.elevenlabs_usage;
  const elevenlabsReady = status?.worker.elevenlabs_configured;

  const loadElevenLabsVoices = async () => {
    setBusy(true);
    setError(null);
    try {
      const voices = await fetchElevenLabsVoices();
      setElevenLabsVoices(voices);
      if (!elevenLabsVoiceId && voices[0]) setElevenLabsVoiceId(voices[0].voice_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'ElevenLabs-Stimmen konnten nicht geladen werden.');
    } finally {
      setBusy(false);
    }
  };

  const saveElevenLabsVoice = async () => {
    if (!elevenLabsVoiceId) return;
    setBusy(true);
    setError(null);
    try {
      await selectElevenLabsVoice(elevenLabsVoiceId);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'ElevenLabs-Stimme konnte nicht gespeichert werden.');
    } finally {
      setBusy(false);
    }
  };

  const saveLimits = async () => {
    const monthly = Number.parseInt(monthlyLimit, 10);
    const perResponse = Number.parseInt(responseLimit, 10);
    if (!Number.isFinite(monthly) || !Number.isFinite(perResponse) || monthly < 0 || perResponse < 0) {
      setError('Kostenlimits müssen nicht-negative ganze Zahlen sein. 0 deaktiviert ElevenLabs.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateVoiceLimits(monthly, perResponse);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Kostenlimits konnten nicht gespeichert werden.');
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
            ElevenLabs · Chatterbox Offline-Fallback · Piper Notfallstimme · Deutsch
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void generate()}
          className="rounded-lg px-3 py-2 text-sm disabled:opacity-40 focus-visible:outline-2"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          {busy ? 'Wird erzeugt…' : elevenlabsReady ? 'Proben erzeugen (ElevenLabs kostenpflichtig)' : 'Lokale Proben erzeugen'}
        </button>
      </div>

      {error && <p role="alert" className="mt-3 text-sm" style={{ color: 'var(--color-error)' }}>{error}</p>}
      {busy && (
        <p role="status" className="mt-3 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Die Proben entstehen nacheinander. Stoppe oder schließe die Ansicht nicht während einer laufenden Erzeugung.
        </p>
      )}
      {!status && !error && <p className="mt-4 text-sm">Lokaler Sprachdienst wird geladen…</p>}
      {status && (
        <>
          <div className="mt-4 rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
            <strong>Fester Vergleichstext</strong>
            <p className="mt-1" lang="de">„{status.audition_text}"</p>
            <p className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              Worker: {status.worker.device} · CUDA {status.worker.cuda ? 'bereit' : 'nicht verfügbar'}
            </p>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              ElevenLabs: {elevenlabsReady ? 'konfiguriert' : (
                !status.worker.elevenlabs_api_key_set
                  ? 'API-Key fehlt (ELEVENLABS_API_KEY)'
                  : 'Voice-ID noch nicht eingerichtet'
              )}
              {' · '}Chatterbox {status.worker.chatterbox_loaded ? 'vorgewärmt' : 'lädt bei erster Nutzung'}
              {' · '}Piper {status.worker.piper_loaded ? 'vorgewärmt' : 'lädt bei erster Nutzung'}
            </p>
            {usage && (
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                ElevenLabs-Verbrauch ({usage.month}): ~{usage.characters_used.toLocaleString()} Zeichen
              </p>
            )}
          </div>
          <div className="mt-3 rounded-xl p-3 text-sm" style={{ border: '1px solid var(--color-border)' }}>
            <div className="flex flex-wrap items-end gap-2">
              <label className="min-w-[15rem] flex-1">
                <span className="block text-xs font-semibold">Echte ElevenLabs-Stimme</span>
                <select
                  value={elevenLabsVoiceId}
                  onChange={(event) => setElevenLabsVoiceId(event.target.value)}
                  disabled={busy || elevenLabsVoices.length === 0}
                  className="mt-1 w-full rounded-lg px-2 py-2"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
                >
                  {!elevenLabsVoiceId && <option value="">Noch keine Voice-ID gewählt</option>}
                  {elevenLabsVoices.map((voice) => (
                    <option key={voice.voice_id} value={voice.voice_id}>{voice.name} · {voice.category || 'voice'}</option>
                  ))}
                </select>
              </label>
              <button type="button" disabled={busy || !status.worker.elevenlabs_api_key_set} onClick={() => void loadElevenLabsVoices()} className="rounded-lg px-3 py-2 disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
                Stimmen laden
              </button>
              <button type="button" disabled={busy || !elevenLabsVoiceId} onClick={() => void saveElevenLabsVoice()} className="rounded-lg px-3 py-2 disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>
                Stimme prüfen & speichern
              </button>
            </div>
            <p className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              Der API-Key bleibt im Desktop-Schlüsselbund. Die Oberfläche erhält nur Status und Voice-Metadaten, niemals den Key.
              {elevenlabsReady ? ' Eine ElevenLabs-Probe reserviert Zeichen aus dem lokalen Kostenlimit.' : ' Ohne Key und Voice-ID wird keine ElevenLabs-Probe erzeugt.'}
            </p>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="text-xs">Monatslimit (Zeichen)
                <input type="number" min="0" step="1" value={monthlyLimit} onChange={(event) => setMonthlyLimit(event.target.value)} className="mt-1 block w-40 rounded-lg px-2 py-2" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }} />
              </label>
              <label className="text-xs">Limit je Antwort
                <input type="number" min="0" step="1" value={responseLimit} onChange={(event) => setResponseLimit(event.target.value)} className="mt-1 block w-40 rounded-lg px-2 py-2" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }} />
              </label>
              <button type="button" disabled={busy} onClick={() => void saveLimits()} className="rounded-lg px-3 py-2 disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>Limits speichern</button>
            </div>
            <p className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              Reservierung erfolgt vor jedem bezahlten Request; Cache-Treffer verbrauchen das lokale Budget nicht. 0 deaktiviert ElevenLabs und erzwingt lokalen Fallback.
            </p>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {status.profiles.map((profile) => {
              const isSelected = status.selected_voice_id === profile.voice_id;
              return (
                <VoiceProfileCard
                  key={profile.voice_id}
                  profile={profile}
                  audioUrl={audioUrls[profile.voice_id]}
                  selected={isSelected}
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
