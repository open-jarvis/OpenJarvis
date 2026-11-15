import { useCallback, useEffect, useRef, useState } from 'react';
import { ACCEPTED_FILES } from '../Hud/attachmentApi';
import { SPEECH_LANG_LABEL } from '../Hud/speechLang';
import type { Jarvis } from '../Jarvis/useJarvis';
import { IconCamera, IconClip, IconMic, IconSend, IconSpeaker, IconWave } from './icons';
import { greeting } from './zenMath';

const SUGGESTIONS = [
  'Plan my day around my habits',
  'Add a habit to read 20 pages at 8:30 pm',
  'How is my week going?',
  'Remind me every evening at 9 to journal',
];

const MODE_LABEL: Record<Jarvis['mode'], string> = {
  idle: 'Ready',
  listening: 'Listening…',
  transcribing: 'Understanding…',
  thinking: 'Thinking…',
  speaking: 'Speaking',
  offline: 'Offline',
};

/** Reveals text progressively so replies that arrive in one chunk still type out. */
function Typewriter({ text, onTick }: { text: string; onTick?: () => void }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (shown >= text.length) return;
    const step = Math.max(1, Math.ceil((text.length - shown) / 40));
    const t = setTimeout(() => { setShown((n) => Math.min(text.length, n + step)); onTick?.(); }, 18);
    return () => clearTimeout(t);
  }, [shown, text, onTick]);
  return <>{text.slice(0, shown)}{shown < text.length && <span className="zen-caret" />}</>;
}

export function ConsoleCard({ j, inputRef }: { j: Jarvis; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const transcriptRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const scroll = useCallback(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);
  useEffect(scroll, [j.messages, scroll]);

  const listening = j.mode === 'listening';

  return (
    <section className={`zen-card zen-console zen-console--${j.mode}`} id="zen-console" aria-label="Jarvis">
      <header className="zen-console__head">
        <div className="zen-console__title">
          <span className={`zen-pulse zen-pulse--${j.mode}`} aria-hidden="true" />
          <div>
            <strong>J.A.R.V.I.S.</strong>
            <span>{MODE_LABEL[j.mode]}</span>
          </div>
        </div>
        <div className="zen-console__status">
          <span className={`zen-chip ${j.online ? 'on' : 'off'}`}>Core</span>
          <span className={`zen-chip ${j.claudeReady ? 'on' : 'off'}`} title={j.claudeReady ? 'Claude is linked' : 'Set ANTHROPIC_API_KEY to link Claude'}>Claude</span>
          <span className={`zen-chip ${j.gptReady ? 'on' : 'off'}`} title={j.gptReady ? 'ChatGPT is linked' : 'Set OPENAI_API_KEY to link ChatGPT'}>GPT</span>
          <select
            className="zen-select"
            value={j.hudModel}
            onChange={(e) => { j.chooseModel(e.target.value); j.addLog(`Model: ${e.target.value}`, 'ok'); }}
            aria-label="Model"
            title="AUTO keeps everyday chat local and sends hard work to Claude or ChatGPT when linked"
          >
            <option value="auto">Auto routing</option>
            {j.models.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
          </select>
        </div>
      </header>

      {j.tabs.length > 0 && (
        <div className="zen-tabs" role="tablist" aria-label="Questions">
          {j.tabs.map((t) => (
            <div key={t.id} className={`zen-tab ${t.id === j.currentTab?.id ? 'is-active' : ''}`}>
              <button type="button" role="tab" aria-selected={t.id === j.currentTab?.id} title={t.msgs[0]?.content} onClick={() => j.setActiveTab(t.id)}>
                {t.label}
              </button>
              <button type="button" className="zen-tab__x" aria-label={`Close ${t.label}`} onClick={() => j.closeTab(t.id)}>×</button>
            </div>
          ))}
        </div>
      )}

      <div className="zen-transcript" ref={transcriptRef} aria-live="polite">
        {j.messages.length === 0 ? (
          <div className="zen-transcript__empty">
            <p><strong>{greeting()}.</strong> Tap the diamond or the mic to talk, or type below.</p>
            <div className="zen-suggest">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" disabled={j.busy} onClick={() => void j.send(s)}>{s}</button>
              ))}
            </div>
          </div>
        ) : (
          (j.currentTab?.msgs ?? []).map((m) => (
            <div key={m.id} className={`zen-msg zen-msg--${m.role}`}>
              <p>
                {!m.content ? <span className="zen-typing"><i /><i /><i /></span>
                  : m.id === j.lastReplyId ? <Typewriter text={m.content} onTick={scroll} /> : m.content}
              </p>
              {m.files && m.files.length > 0 && (
                <span className="zen-msg__files">{m.files.map((f) => <span key={f}>📎 {f}</span>)}</span>
              )}
            </div>
          ))
        )}
      </div>

      {(j.pending.length > 0 || j.uploadingCount > 0) && (
        <div className="zen-attach-tray" aria-label="Attached files">
          {j.pending.map((a) => (
            <span key={a.id} className={`zen-attach ${a.status === 'describing' ? 'is-busy' : ''} ${a.status === 'failed' ? 'is-failed' : ''}`} title={a.error || a.name}>
              <b>{a.kind === 'image' ? 'IMG' : a.kind === 'document' ? 'DOC' : 'TXT'}</b>
              <span>{a.name}</span>
              <em>{a.status === 'describing' ? 'reading…' : a.status === 'failed' ? 'unreadable' : 'ready'}</em>
              <button type="button" aria-label={`Remove ${a.name}`} onClick={() => j.setPending((p) => p.filter((x) => x.id !== a.id))}>×</button>
            </span>
          ))}
          {j.uploadingCount > 0 && <span className="zen-attach is-busy"><span>Uploading {j.uploadingCount}…</span></span>}
        </div>
      )}

      <form className="zen-command" onSubmit={(e) => { e.preventDefault(); void j.send(j.input); }}>
        <input ref={fileRef} type="file" multiple hidden accept={ACCEPTED_FILES} onChange={(e) => { void j.addFiles(Array.from(e.target.files ?? []), 'upload'); e.target.value = ''; }} />
        <button type="button" className="zen-icon-btn" onClick={() => fileRef.current?.click()} aria-label="Attach files" title="Attach files (or drop / paste them anywhere)"><IconClip /></button>
        <button type="button" className="zen-icon-btn" onClick={() => void j.takeScreenshot()} aria-label="Capture screen" title="Capture your screen and attach it"><IconCamera /></button>
        <input
          ref={inputRef}
          className="zen-command__input"
          value={j.input}
          onChange={(e) => j.setInput(e.target.value)}
          placeholder={j.online ? 'Ask Jarvis anything…' : 'Waiting for Jarvis to come online…'}
          aria-label="Command"
          autoComplete="off"
        />
        <button
          type="button"
          className={`zen-icon-btn ${listening ? 'is-live' : ''}`}
          onClick={() => (listening ? j.stopListening() : void j.startListening())}
          disabled={j.phase === 'thinking' || j.phase === 'streaming' || j.phase === 'transcribing'}
          aria-label={listening ? 'Stop listening' : 'Talk'}
        >
          <IconMic />
        </button>
        {j.busy && j.phase !== 'listening' && j.phase !== 'transcribing' ? (
          <button type="button" className="zen-btn zen-btn--warn" onClick={j.abort}>Stop</button>
        ) : (
          <button type="submit" className="zen-send" disabled={!j.input.trim() && j.pending.length === 0} aria-label="Send"><IconSend /></button>
        )}
      </form>

      <div className="zen-toggles">
        <button type="button" className={`zen-toggle ${j.voiceOut ? 'is-on' : ''}`} aria-pressed={j.voiceOut} onClick={() => { j.setVoiceOut((v) => !v); if (j.voiceOut) j.stopVoice(); }} title="Speak replies aloud">
          <IconSpeaker /> Voice {j.voiceOut ? 'on' : 'off'}
        </button>
        <button type="button" className={`zen-toggle ${j.handsFree ? 'is-on' : ''}`} aria-pressed={j.handsFree} onClick={j.toggleHandsFree} title="Hands-free: Jarvis listens, sends when you pause, answers, then listens again">
          <IconWave /> Hands-free {j.handsFree ? 'on' : 'off'}
        </button>
        <button type="button" className="zen-toggle is-on zen-toggle--lang" onClick={j.cycleLanguage} title="Spoken language: AUTO detects English or Malayalam" aria-label={`Spoken language: ${SPEECH_LANG_LABEL[j.speechLang]}`}>
          {SPEECH_LANG_LABEL[j.speechLang]}
        </button>
      </div>
    </section>
  );
}
