import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router';
import { MessageSquare, Power } from 'lucide-react';
import { ApprovalBell } from '../components/ApprovalBell';
import { ActivityFeed, SystemPanel } from '../components/Hud/HudPanels';
import { ProjectionStage } from '../components/Hud/ProjectionStage';
import { ReactorCore } from '../components/Hud/ReactorCore';
import { useHudSession } from '../hooks/useHudSession';
import type { HudPhase } from '../hooks/useHudSession';
import '../components/Hud/hud.css';

const PHASE_LABELS: Record<HudPhase, string> = {
  standby: 'En espera',
  idle: 'A la escucha',
  hearing: 'Escuchando',
  transcribing: 'Transcribiendo',
  thinking: 'Procesando',
  speaking: 'Respondiendo',
};

const clockFormat = new Intl.DateTimeFormat('es', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
const dateFormat = new Intl.DateTimeFormat('es', { weekday: 'short', day: 'numeric', month: 'short' });

/** Reloj aislado: su actualización por segundo no re-renderiza el resto del HUD. */
function HudClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <time className="hud-clock" dateTime={now.toISOString()}>
      <strong>{clockFormat.format(now)}</strong>
      <span>{dateFormat.format(now).replace(/[.,]/g, '')}</span>
    </time>
  );
}

/** Las teclas del HUD no deben activarse mientras se escribe o se usa un control. */
function isTypingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest('input, textarea, button, a, select') !== null;
}

/**
 * Interfaz de voz a pantalla completa: núcleo central, estado del sistema,
 * actividad del agente y proyección de resultados.
 */
export function HudPage() {
  const session = useHudSession();
  const { phase, active, interrupt, startPushToTalk, stopPushToTalk, submit } = session;
  const [draft, setDraft] = useState('');

  // Espacio mantenido = hablar sin decir "Jarvis"; Escape = interrumpir.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Esc interrumpe siempre, también justo después de escribir una orden.
      if (event.key === 'Escape') {
        interrupt();
        return;
      }
      if (isTypingTarget(event.target)) return;
      if (event.code === 'Space' && !event.repeat) {
        event.preventDefault();
        startPushToTalk();
      }
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'Space') stopPushToTalk();
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [interrupt, startPushToTalk, stopPushToTalk]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit(draft);
    setDraft('');
  };

  const micUnavailable = session.micStatus === 'denied' || session.micStatus === 'unsupported';

  return (
    <div className="hud-root" data-phase={phase}>
      <header className="hud-header">
        <div className="hud-brand">
          <strong>JARVIS</strong>
          <span className={`hud-status${session.serverOnline === false ? ' is-offline' : ''}`}>
            {session.serverOnline === false ? 'Servidor desconectado' : active ? 'En línea' : 'En espera'}
          </span>
        </div>
        <HudClock />
        <nav className="hud-header-actions" aria-label="Controles">
          <div className="hud-approvals">
            <ApprovalBell />
          </div>
          {active && (
            <button
              type="button"
              className="hud-icon-button"
              onClick={session.deactivate}
              aria-label="Apagar micrófono y voz"
              title="Apagar micrófono y voz"
            >
              <Power size={16} />
            </button>
          )}
          <Link to="/" className="hud-icon-button" aria-label="Volver al chat" title="Volver al chat">
            <MessageSquare size={16} />
          </Link>
        </nav>
      </header>

      <aside className="hud-column hud-left">
        <SystemPanel
          model={session.model}
          stats={session.stats}
          micStatus={session.micStatus}
          voiceOutput={session.voiceOutput}
          active={active}
        />
      </aside>

      <main className="hud-center">
        <div className="hud-core">
          <ReactorCore phase={phase} getLevel={session.getLevel} />
          {!active && (
            <button type="button" className="hud-start" onClick={() => void session.activate()}>
              Iniciar sistemas
            </button>
          )}
        </div>
        <p className="hud-phase" role="status">
          {PHASE_LABELS[phase]}
        </p>
        <p className="hud-heard">{session.heardText && `«${session.heardText}»`}</p>
        <p className="hud-hint">
          {!active
            ? 'Se pedirá permiso de micrófono. El audio se procesa en este equipo.'
            : micUnavailable
              ? 'Micrófono no disponible: escriba su orden abajo.'
              : 'Diga «Jarvis» y su orden · mantenga Espacio para hablar · Esc para interrumpir'}
        </p>
      </main>

      <aside className="hud-column hud-right">
        <ActivityFeed entries={session.activity} />
        <ProjectionStage cards={session.cards} onDismiss={session.dismissCard} />
      </aside>

      <footer className="hud-footer">
        <p className="hud-caption" aria-live="polite">
          {session.caption}
        </p>
        <form className="hud-command" onSubmit={handleSubmit}>
          <span aria-hidden="true">&gt;</span>
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Escriba una orden…"
            aria-label="Orden por texto"
            autoComplete="off"
          />
        </form>
      </footer>
    </div>
  );
}
