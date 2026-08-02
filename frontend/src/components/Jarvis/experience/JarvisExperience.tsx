import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Bug,
  Check,
  ChevronRight,
  CircleStop,
  Menu,
  MessageSquareText,
  Mic,
  MicOff,
  Plus,
  Send,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Square,
  Volume2,
  X,
} from 'lucide-react';
import type { CanonicalTaskEvent, PendingApproval } from '../../../lib/api';
import { JarvisAvatar, voiceStateLabel } from './JarvisAvatar';
import type { JarvisMode, JarvisPreferences } from './preferences';
import { MockVoiceAdapter } from './voiceAdapter';
import type { JarvisVoiceState, VoiceAdapterSnapshot } from './voiceAdapter';
import { useAnimationBudget } from './useAnimationBudget';

export interface JarvisExperienceProps {
  sessionId: string;
  timeline: CanonicalTaskEvent[];
  activeTaskStatus: string | null;
  draft: string;
  sending: boolean;
  submitBlocked: boolean;
  error: string | null;
  voice: VoiceAdapterSnapshot;
  sttAvailable: boolean;
  ttsAvailable: boolean;
  speechLanguage: string;
  preferences: JarvisPreferences;
  approvals: PendingApproval[];
  decisionBusy: string | null;
  onPreferencesChange: (patch: Partial<JarvisPreferences>) => void;
  onDraftChange: (draft: string) => void;
  onSubmit: (message?: string, inputMode?: 'text' | 'voice') => void | Promise<void>;
  onToggleMicrophone: (submitTranscript: boolean) => void | Promise<void>;
  onStop: () => void | Promise<void>;
  onNewConversation: () => void | Promise<void>;
  onLanguageChange: (language: string) => void;
  onApprovalDecision: (approval: PendingApproval, allow: boolean) => void | Promise<void>;
}

export interface VisibleMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  occurredAt: string;
}

export function visibleConversation(events: CanonicalTaskEvent[]): VisibleMessage[] {
  return events.flatMap((event) => {
    if (!['chat.user_message', 'chat.assistant_message'].includes(event.event_type)) return [];
    const content = event.payload && typeof event.payload.content === 'string'
      ? event.payload.content.trim()
      : '';
    if (!content) return [];
    return [{
      id: event.event_id,
      role: event.event_type === 'chat.user_message' ? 'user' as const : 'assistant' as const,
      content,
      occurredAt: event.occurred_at,
    }];
  });
}

export function userSafeError(message: string | null): string | null {
  if (!message) return null;
  const normalized = message.toLowerCase();
  if (normalized.includes('microphone') || normalized.includes('speech') || normalized.includes('record')) {
    return 'Die Sprachfunktion ist gerade nicht verfügbar. Du kannst weiterhin den Textmodus verwenden.';
  }
  if (normalized.includes('server') || normalized.includes('network') || normalized.includes('reach')) {
    return 'Die Verbindung zu Jarvis ist unterbrochen. Die Wiederherstellung läuft.';
  }
  if (normalized.includes('task') || normalized.includes('turn') || normalized.includes('session')) {
    return 'Diese Unterhaltung kann nicht fortgesetzt werden. Starte eine neue Unterhaltung.';
  }
  return 'Jarvis konnte die Aktion nicht abschließen. Versuche es bitte erneut.';
}

function usePanelFocus(open: boolean, onClose: () => void) {
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    const focusable = panelRef.current?.querySelector<HTMLElement>('button:not(:disabled), select, textarea, input');
    focusable?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [open]);

  return panelRef;
}

function ModeSwitcher({ mode, onChange }: { mode: JarvisMode; onChange: (mode: JarvisMode) => void }) {
  return (
    <div className="jarvis-mode-switcher" role="group" aria-label="Darstellungsmodus">
      <button type="button" aria-pressed={mode === 'talk'} onClick={() => onChange('talk')}>
        <Sparkles size={15} /> Talk
      </button>
      <button type="button" aria-pressed={mode === 'text'} onClick={() => onChange('text')}>
        <MessageSquareText size={15} /> Text
      </button>
    </div>
  );
}

export function MenuPanel({
  open,
  mode,
  developerMode,
  onClose,
  onModeChange,
  onNewConversation,
  onOpenSettings,
  onOpenDeveloper,
}: {
  open: boolean;
  mode: JarvisMode;
  developerMode: boolean;
  onClose: () => void;
  onModeChange: (mode: JarvisMode) => void;
  onNewConversation: () => void;
  onOpenSettings: () => void;
  onOpenDeveloper: () => void;
}) {
  const panelRef = usePanelFocus(open, onClose);
  if (!open) return null;
  const chooseMode = (next: JarvisMode) => {
    onModeChange(next);
    onClose();
  };
  return (
    <div className="jarvis-overlay" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <div className="jarvis-menu" ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="jarvis-menu-title">
        <div className="jarvis-panel-heading">
          <div>
            <span className="jarvis-kicker">JARVIS</span>
            <h2 id="jarvis-menu-title">Menü</h2>
          </div>
          <button type="button" className="jarvis-icon-button" onClick={onClose} aria-label="Menü schließen"><X size={18} /></button>
        </div>
        <nav aria-label="Jarvis-Menü" className="jarvis-menu__items">
          <button type="button" onClick={() => { onNewConversation(); onClose(); }}>
            <Plus size={17} /><span>Neue Unterhaltung</span><ChevronRight size={15} />
          </button>
          <button type="button" aria-current={mode === 'talk' ? 'page' : undefined} onClick={() => chooseMode('talk')}>
            <Sparkles size={17} /><span>Talk-Modus</span>{mode === 'talk' ? <Check size={15} /> : <ChevronRight size={15} />}
          </button>
          <button type="button" aria-current={mode === 'text' ? 'page' : undefined} onClick={() => chooseMode('text')}>
            <MessageSquareText size={17} /><span>Text-Modus</span>{mode === 'text' ? <Check size={15} /> : <ChevronRight size={15} />}
          </button>
          <button type="button" onClick={() => { onOpenSettings(); onClose(); }}>
            <SlidersHorizontal size={17} /><span>Avatar & Animationen</span><ChevronRight size={15} />
          </button>
          <button type="button" onClick={() => { onOpenSettings(); onClose(); }}>
            <Settings2 size={17} /><span>Einstellungen</span><ChevronRight size={15} />
          </button>
          {developerMode && (
            <button type="button" onClick={() => { onOpenDeveloper(); onClose(); }}>
              <Bug size={17} /><span>Entwicklermodus</span><ChevronRight size={15} />
            </button>
          )}
        </nav>
        <p className="jarvis-menu__note">Verlauf und interne Arbeit bleiben in der normalen Ansicht verborgen.</p>
      </div>
    </div>
  );
}

export function SettingsPanel({
  open,
  preferences,
  sttAvailable,
  ttsAvailable,
  language,
  onClose,
  onChange,
  onLanguageChange,
}: {
  open: boolean;
  preferences: JarvisPreferences;
  sttAvailable: boolean;
  ttsAvailable: boolean;
  language: string;
  onClose: () => void;
  onChange: (patch: Partial<JarvisPreferences>) => void;
  onLanguageChange: (language: string) => void;
}) {
  const panelRef = usePanelFocus(open, onClose);
  if (!open) return null;
  return (
    <div className="jarvis-overlay jarvis-overlay--right" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <div className="jarvis-settings" ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="jarvis-settings-title">
        <div className="jarvis-panel-heading">
          <div>
            <span className="jarvis-kicker">Erscheinungsbild</span>
            <h2 id="jarvis-settings-title">Avatar & Animationen</h2>
          </div>
          <button type="button" className="jarvis-icon-button" onClick={onClose} aria-label="Einstellungen schließen"><X size={18} /></button>
        </div>

        <section className="jarvis-settings__section" aria-labelledby="animation-settings-title">
          <h3 id="animation-settings-title">Animation</h3>
          <label>
            <span>Animationsqualität</span>
            <select value={preferences.animationQuality} onChange={(event) => onChange({ animationQuality: event.target.value as JarvisPreferences['animationQuality'] })}>
              <option value="off">Aus</option>
              <option value="reduced">Reduziert</option>
              <option value="standard">Standard</option>
              <option value="high">Hoch</option>
            </select>
          </label>
          <label>
            <span>Bewegungsintensität</span>
            <select value={preferences.movementIntensity} onChange={(event) => onChange({ movementIntensity: event.target.value as JarvisPreferences['movementIntensity'] })}>
              <option value="very-low">Sehr niedrig</option>
              <option value="low">Niedrig</option>
              <option value="standard">Standard</option>
              <option value="high">Hoch</option>
            </select>
          </label>
          <label>
            <span>Mundbewegung</span>
            <select value={preferences.mouthMovement} onChange={(event) => onChange({ mouthMovement: event.target.value as JarvisPreferences['mouthMovement'] })}>
              <option value="off">Aus</option>
              <option value="subtle">Dezent</option>
              <option value="normal">Normal</option>
            </select>
          </label>
          <p className="jarvis-settings__hint">Für dieses Bild ist die Mundbewegung aus Qualitätsgründen standardmäßig deaktiviert. Sie verändert niemals Augen oder Stirn.</p>
          <label className="jarvis-toggle">
            <span>Reduzierte Bewegung</span>
            <input type="checkbox" checked={preferences.reducedMotion} onChange={(event) => onChange({ reducedMotion: event.target.checked })} />
          </label>
          <label className="jarvis-toggle">
            <span>Avatar im Textmodus</span>
            <input type="checkbox" checked={preferences.showAvatarInTextMode} onChange={(event) => onChange({ showAvatarInTextMode: event.target.checked })} />
          </label>
        </section>

        <section className="jarvis-settings__section" aria-labelledby="voice-settings-title">
          <h3 id="voice-settings-title">Sprachschnittstelle</h3>
          <div className="jarvis-capability-row"><span>Mikrofonadapter</span><strong>{sttAvailable ? 'Bereit' : 'Nicht verfügbar'}</strong></div>
          <div className="jarvis-capability-row"><span>Wiedergabeadapter</span><strong>{ttsAvailable ? 'Bereit' : 'Nicht verfügbar'}</strong></div>
          <label>
            <span>Sprache</span>
            <select value={language} onChange={(event) => onLanguageChange(event.target.value)}>
              <option value="de-DE">Deutsch</option>
              <option value="en-US">English</option>
              <option value="ar-SA">العربية</option>
            </select>
          </label>
          <p className="jarvis-settings__hint">Diese Ansicht konsumiert nur den Voice-Vertrag. Auswahl und Erzeugung der Stimme bleiben im separaten Sprachsystem.</p>
        </section>

        <section className="jarvis-settings__section" aria-labelledby="developer-settings-title">
          <h3 id="developer-settings-title">Entwicklung</h3>
          <label className="jarvis-toggle">
            <span>Entwicklermodus</span>
            <input type="checkbox" checked={preferences.developerMode} onChange={(event) => onChange({ developerMode: event.target.checked, mockVoiceEnabled: event.target.checked ? preferences.mockVoiceEnabled : false })} />
          </label>
          <p className="jarvis-settings__hint">Standardmäßig aus. Zeigt nur UI- und Integrationsdiagnosen, niemals Prompts, Gedankengänge oder geheime Werte.</p>
        </section>
      </div>
    </div>
  );
}

function DeveloperPanel({
  open,
  sessionId,
  voice,
  mockEnabled,
  fps,
  tier,
  onClose,
  onMockEnabled,
  onMockState,
}: {
  open: boolean;
  sessionId: string;
  voice: VoiceAdapterSnapshot;
  mockEnabled: boolean;
  fps: number | null;
  tier: number;
  onClose: () => void;
  onMockEnabled: (enabled: boolean) => void;
  onMockState: (state: JarvisVoiceState) => void;
}) {
  const panelRef = usePanelFocus(open, onClose);
  if (!open) return null;
  const states: JarvisVoiceState[] = ['idle', 'listening', 'processing', 'speaking', 'interrupted', 'error', 'offline'];
  return (
    <div className="jarvis-overlay jarvis-overlay--right" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <div className="jarvis-developer" ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="jarvis-developer-title">
        <div className="jarvis-panel-heading">
          <div><span className="jarvis-kicker">Nur Entwicklung</span><h2 id="jarvis-developer-title">UI-Diagnose</h2></div>
          <button type="button" className="jarvis-icon-button" onClick={onClose} aria-label="Entwicklermodus schließen"><X size={18} /></button>
        </div>
        <dl className="jarvis-developer__metrics">
          <div><dt>Session</dt><dd>{sessionId.slice(-8)}</dd></div>
          <div><dt>Voice state</dt><dd>{voice.state}</dd></div>
          <div><dt>Lautstärke</dt><dd>{voice.volumeLevel.toFixed(2)}</dd></div>
          <div><dt>FPS</dt><dd>{fps ?? 'wird gemessen'}</dd></div>
          <div><dt>Fallback</dt><dd>Stufe {tier}</dd></div>
        </dl>
        <label className="jarvis-toggle jarvis-developer__toggle">
          <span>Voice-Mock verwenden</span>
          <input type="checkbox" checked={mockEnabled} onChange={(event) => onMockEnabled(event.target.checked)} />
        </label>
        <div className="jarvis-developer__states" aria-label="Simulierte Voice-Zustände">
          {states.map((state) => (
            <button key={state} type="button" disabled={!mockEnabled} aria-pressed={voice.state === state} onClick={() => onMockState(state)}>
              {state}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function ApprovalPrompt({
  approval,
  busy,
  onDecision,
}: {
  approval: PendingApproval;
  busy: boolean;
  onDecision: (allow: boolean) => void;
}) {
  return (
    <section className="jarvis-approval" role="dialog" aria-modal="true" aria-labelledby={`approval-title-${approval.id}`}>
      <span className="jarvis-kicker">Deine Entscheidung</span>
      <h2 id={`approval-title-${approval.id}`}>Jarvis benötigt eine Freigabe</h2>
      <p>{approval.effect || approval.description || 'Die nächste Aktion kann Auswirkungen außerhalb der Unterhaltung haben.'}</p>
      <div className="jarvis-approval__actions">
        <button type="button" disabled={busy} onClick={() => onDecision(false)}>Ablehnen</button>
        <button type="button" className="jarvis-primary-button" disabled={busy} onClick={() => onDecision(true)}>Einmal erlauben</button>
      </div>
    </section>
  );
}

function TalkView({
  voice,
  preferences,
  fallbackTier,
  microphoneAvailable,
  sending,
  onToggleMicrophone,
  onStop,
}: {
  voice: VoiceAdapterSnapshot;
  preferences: JarvisPreferences;
  fallbackTier: 1 | 2 | 3 | 4;
  microphoneAvailable: boolean;
  sending: boolean;
  onToggleMicrophone: () => void;
  onStop: () => void;
}) {
  const listening = voice.state === 'listening';
  const active = sending || ['processing', 'speaking'].includes(voice.state);
  return (
    <main className="jarvis-talk" aria-label="Jarvis Talk-Modus">
      <div className="jarvis-talk__avatar">
        <JarvisAvatar voice={voice} preferences={preferences} fallbackTier={fallbackTier} />
      </div>
      <div className="jarvis-talk__state" role="status" aria-live="polite">
        <i data-state={voice.state} aria-hidden="true" />
        <span>{voiceStateLabel(voice.state)}</span>
      </div>
      <div className="jarvis-talk__controls" aria-label="Talk-Steuerung">
        <button
          type="button"
          className={`jarvis-talk__mic ${listening ? 'is-active' : ''}`}
          disabled={!microphoneAvailable || sending}
          aria-pressed={listening}
          aria-label={listening ? 'Zuhören beenden und senden' : 'Jarvis zuhören lassen'}
          onClick={onToggleMicrophone}
        >
          {microphoneAvailable ? (listening ? <Square size={22} /> : <Mic size={23} />) : <MicOff size={23} />}
        </button>
        {active && (
          <button type="button" className="jarvis-control-button" onClick={onStop} aria-label="Aktuelle Ausgabe stoppen">
            <CircleStop size={20} />
          </button>
        )}
      </div>
    </main>
  );
}

function TextView({
  messages,
  draft,
  voice,
  preferences,
  fallbackTier,
  sending,
  submitBlocked,
  microphoneAvailable,
  onDraftChange,
  onSubmit,
  onToggleMicrophone,
  onStop,
}: {
  messages: VisibleMessage[];
  draft: string;
  voice: VoiceAdapterSnapshot;
  preferences: JarvisPreferences;
  fallbackTier: 1 | 2 | 3 | 4;
  sending: boolean;
  submitBlocked: boolean;
  microphoneAvailable: boolean;
  onDraftChange: (draft: string) => void;
  onSubmit: () => void;
  onToggleMicrophone: () => void;
  onStop: () => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ block: 'nearest' }), [messages.length, sending]);
  return (
    <main className="jarvis-text" aria-label="Jarvis Text-Modus">
      {preferences.showAvatarInTextMode && (
        <div className="jarvis-text__avatar" aria-hidden="true">
          <JarvisAvatar voice={voice} preferences={preferences} fallbackTier={fallbackTier} compact />
        </div>
      )}
      <div className="jarvis-text__conversation" aria-live="polite" aria-busy={sending}>
        {messages.length === 0 ? (
          <section className="jarvis-text__empty">
            <span className="jarvis-kicker">Neue Unterhaltung</span>
            <h1>Was möchtest du wissen?</h1>
            <p>Schreibe direkt oder wechsle jederzeit in den Talk-Modus.</p>
          </section>
        ) : messages.map((message) => (
          <article key={message.id} className={`jarvis-message jarvis-message--${message.role}`} aria-label={message.role === 'user' ? 'Deine Nachricht' : 'Antwort von Jarvis'} dir="auto">
            <span>{message.role === 'user' ? 'Du' : 'Jarvis'}</span>
            {message.role === 'assistant' ? (
              <div className="jarvis-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>
            ) : <p>{message.content}</p>}
          </article>
        ))}
        {sending && <div className="jarvis-text__thinking" role="status"><i /><i /><i /><span className="sr-only">Jarvis verarbeitet</span></div>}
        <div ref={endRef} />
      </div>
      <form className="jarvis-composer" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <label htmlFor="jarvis-message" className="sr-only">Nachricht an Jarvis</label>
        <textarea
          id="jarvis-message"
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
          rows={1}
          dir="auto"
          placeholder="Nachricht an Jarvis"
        />
        <div className="jarvis-composer__actions">
          <button type="button" onClick={onToggleMicrophone} disabled={!microphoneAvailable || sending} aria-label="Spracheingabe">
            {voice.state === 'listening' ? <Square size={18} /> : microphoneAvailable ? <Mic size={18} /> : <MicOff size={18} />}
          </button>
          {(sending || voice.state === 'speaking') ? (
            <button type="button" onClick={onStop} aria-label="Antwort stoppen"><CircleStop size={19} /></button>
          ) : (
            <button type="submit" className="jarvis-primary-button" disabled={!draft.trim() || submitBlocked} aria-label="Nachricht senden"><Send size={18} /></button>
          )}
        </div>
      </form>
    </main>
  );
}

export function JarvisExperience(props: JarvisExperienceProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [developerOpen, setDeveloperOpen] = useState(false);
  const [mockSnapshot, setMockSnapshot] = useState<VoiceAdapterSnapshot | null>(null);
  const mockAdapterRef = useRef<MockVoiceAdapter | null>(null);
  if (!mockAdapterRef.current) mockAdapterRef.current = new MockVoiceAdapter();

  useEffect(() => {
    const adapter = mockAdapterRef.current;
    if (!adapter) return undefined;
    const unsubscribe = adapter.subscribe(setMockSnapshot);
    return () => {
      unsubscribe();
      adapter.dispose();
    };
  }, []);

  const activeVoice = props.preferences.developerMode && props.preferences.mockVoiceEnabled && mockSnapshot
    ? mockSnapshot
    : props.voice;
  const animation = useAnimationBudget(props.preferences.animationQuality, props.preferences.reducedMotion);
  const messages = useMemo(() => visibleConversation(props.timeline), [props.timeline]);
  const friendlyError = userSafeError(props.error || activeVoice.errorMessage);
  const currentApproval = props.approvals[0] ?? null;

  const changeMode = (mode: JarvisMode) => props.onPreferencesChange({ mode });
  const newConversation = () => {
    mockAdapterRef.current?.startNewConversation();
    void props.onNewConversation();
  };
  const toggleMicrophone = () => {
    if (props.preferences.mockVoiceEnabled && props.preferences.developerMode) {
      if (activeVoice.state === 'listening') mockAdapterRef.current?.stopListening();
      else mockAdapterRef.current?.startListening();
      return;
    }
    void props.onToggleMicrophone(props.preferences.mode === 'talk');
  };
  const stop = () => {
    mockAdapterRef.current?.interruptSpeech();
    void props.onStop();
  };

  return (
    <div className="jarvis-experience" data-mode={props.preferences.mode} data-page-visible={animation.pageVisible ? 'true' : 'false'}>
      <div className="jarvis-experience__grain" aria-hidden="true" />
      <button type="button" className="jarvis-menu-trigger" onClick={() => setMenuOpen(true)} aria-label="Jarvis-Menü öffnen"><Menu size={20} /></button>
      <div className="jarvis-topbar">
        <span className="jarvis-wordmark">JARVIS</span>
        <ModeSwitcher mode={props.preferences.mode} onChange={changeMode} />
      </div>
      <button type="button" className="jarvis-new-chat" onClick={newConversation} aria-label="Neue Unterhaltung"><Plus size={18} /><span>Neu</span></button>

      {props.preferences.mode === 'talk' ? (
        <TalkView
          voice={activeVoice}
          preferences={props.preferences}
          fallbackTier={animation.tier}
          microphoneAvailable={props.sttAvailable || props.preferences.mockVoiceEnabled}
          sending={props.sending}
          onToggleMicrophone={toggleMicrophone}
          onStop={stop}
        />
      ) : (
        <TextView
          messages={messages}
          draft={props.draft}
          voice={activeVoice}
          preferences={props.preferences}
          fallbackTier={animation.tier}
          sending={props.sending}
          submitBlocked={props.submitBlocked}
          microphoneAvailable={props.sttAvailable || props.preferences.mockVoiceEnabled}
          onDraftChange={props.onDraftChange}
          onSubmit={() => void props.onSubmit()}
          onToggleMicrophone={toggleMicrophone}
          onStop={stop}
        />
      )}

      {friendlyError && <div className="jarvis-friendly-error" role="alert">{friendlyError}</div>}
      {currentApproval && (
        <ApprovalPrompt
          approval={currentApproval}
          busy={props.decisionBusy === currentApproval.id}
          onDecision={(allow) => void props.onApprovalDecision(currentApproval, allow)}
        />
      )}

      <MenuPanel
        open={menuOpen}
        mode={props.preferences.mode}
        developerMode={props.preferences.developerMode}
        onClose={() => setMenuOpen(false)}
        onModeChange={changeMode}
        onNewConversation={newConversation}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenDeveloper={() => setDeveloperOpen(true)}
      />
      <SettingsPanel
        open={settingsOpen}
        preferences={props.preferences}
        sttAvailable={props.sttAvailable}
        ttsAvailable={props.ttsAvailable}
        language={props.speechLanguage}
        onClose={() => setSettingsOpen(false)}
        onChange={props.onPreferencesChange}
        onLanguageChange={props.onLanguageChange}
      />
      {props.preferences.developerMode && (
        <DeveloperPanel
          open={developerOpen}
          sessionId={props.sessionId}
          voice={activeVoice}
          mockEnabled={props.preferences.mockVoiceEnabled}
          fps={animation.fps}
          tier={animation.tier}
          onClose={() => setDeveloperOpen(false)}
          onMockEnabled={(enabled) => props.onPreferencesChange({ mockVoiceEnabled: enabled })}
          onMockState={(state) => mockAdapterRef.current?.setState(state)}
        />
      )}
    </div>
  );
}
