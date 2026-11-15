/**
 * Jarvis home screen: a light, focused dashboard (profile, progress, habits,
 * focus, journal, quotes, mission) with Jarvis built in - chat in the
 * console, voice on the diamond in the dock.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { ApprovalDock } from '../components/Hud/ApprovalDock';
import { AttachmentsDeck } from '../components/Hud/AttachmentsDeck';
import { AutomationsDeck } from '../components/Hud/AutomationsDeck';
import { useJarvis } from '../components/Jarvis/useJarvis';
import { ConsoleCard } from '../components/Zenith/ConsoleCard';
import { FocusCard, FocusOverlay } from '../components/Zenith/FocusCard';
import { MissionCard, ReminderCard, SystemCard } from '../components/Zenith/MissionCards';
import { JournalCard, QuotesCard } from '../components/Zenith/NotesCards';
import { ProfileCard, type NavItem } from '../components/Zenith/ProfileCard';
import { KaizenCard, ProgressRingCard, ScheduleCard, StreakCard } from '../components/Zenith/ProgressCards';
import { ZenDock } from '../components/Zenith/ZenDock';
import { Diamond } from '../components/Zenith/ZenArt';
import {
  IconBook, IconChart, IconClock, IconFolder, IconGrid, IconQuote, IconTarget, IconUser,
} from '../components/Zenith/icons';
import { useLife } from '../components/Zenith/lifeApi';
import '../components/Hud/hud.css';
import '../components/Hud/hud-automation.css';
import '../components/Hud/hud-attachments.css';
import '../components/Zenith/zenith.css';

const scrollToId = (id: string) =>
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 15_000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="zen-top__clock">
      {now.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })}
      <b>{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b>
    </span>
  );
}

export function HudPage() {
  const navigate = useNavigate();
  const j = useJarvis();
  const life = useLife();
  const [deckOpen, setDeckOpen] = useState(false);
  const [vaultOpen, setVaultOpen] = useState(false);
  const [focusOpen, setFocusOpen] = useState(false);
  const [journalKey, setJournalKey] = useState(0);
  const [section, setSection] = useState('dashboard');
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const { refresh: refreshLife } = life;

  const changed = useCallback(() => {
    void refreshLife();
    setJournalKey((k) => k + 1);
  }, [refreshLife]);

  // Jarvis may have added a habit or journal entry: refresh after each reply.
  useEffect(() => {
    if (j.replyCount) changed();
  }, [j.replyCount, changed]);

  // "/" focuses the command box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName);
      if (e.key === '/' && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const go = (id: string, target: string) => { setSection(id); scrollToId(target); };
  const activeRoutines = j.automations.items.filter((a) => a.status === 'active').length;

  const nav: NavItem[] = [
    { id: 'dashboard', label: 'Dashboard', icon: <IconGrid />, onSelect: () => go('dashboard', 'zen-top') },
    { id: 'jarvis', label: 'Jarvis', icon: <IconUser />, onSelect: () => { go('jarvis', 'zen-console'); inputRef.current?.focus(); } },
    { id: 'habits', label: 'Habits', icon: <IconTarget />, onSelect: () => go('habits', 'zen-schedule') },
    { id: 'focus', label: 'Focus mode', icon: <IconChart />, onSelect: () => setFocusOpen(true) },
    { id: 'journal', label: 'Journal', icon: <IconBook />, onSelect: () => go('journal', 'zen-journal') },
    { id: 'quotes', label: 'Quotes', icon: <IconQuote />, onSelect: () => go('quotes', 'zen-quotes') },
    { id: 'routines', label: 'Routines', icon: <IconClock />, onSelect: () => setDeckOpen(true), badge: activeRoutines },
    { id: 'files', label: 'Files', icon: <IconFolder />, onSelect: () => setVaultOpen(true) },
  ];

  const onQuickAction = (a: 'habit' | 'focus' | 'journal' | 'stats' | 'goals') => {
    if (a === 'focus') setFocusOpen(true);
    else if (a === 'habit') go('habits', 'zen-schedule');
    else if (a === 'journal') go('journal', 'zen-journal');
    else if (a === 'stats') go('dashboard', 'zen-top');
    else go('dashboard', 'zen-mission');
  };

  const dragHandlers = {
    onDragEnter: (e: React.DragEvent) => {
      if (!e.dataTransfer.types.includes('Files')) return;
      e.preventDefault();
      dragDepth.current += 1;
      setDragActive(true);
    },
    onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); },
    onDragLeave: () => {
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setDragActive(false);
    },
    onDrop: (e: React.DragEvent) => {
      if (!e.dataTransfer.files.length) return;
      e.preventDefault();
      dragDepth.current = 0;
      setDragActive(false);
      void j.addFiles(Array.from(e.dataTransfer.files), 'drop');
    },
  };

  return (
    <div className={`hud zen zen--${j.mode}`} {...dragHandlers}>
      {dragActive && (
        <div className="zen-drop" aria-hidden="true">
          <div>Drop to attach<small>Documents, spreadsheets, code and images</small></div>
        </div>
      )}

      <header className="zen-top" id="zen-top">
        <div className="zen-brand">
          <Diamond className="zen-brand__gem" />
          <div><strong>JARVIS</strong><span>Personal command center</span></div>
        </div>
        <Clock />
        <div className="zen-top__actions">
          <button type="button" className="zen-btn" onClick={() => setDeckOpen(true)}>
            Routines{activeRoutines > 0 && <span className="zen-badge">{activeRoutines}</span>}
          </button>
          <button type="button" className="zen-btn" onClick={() => setVaultOpen(true)}>Files</button>
          <button type="button" className="zen-btn" onClick={() => navigate('/')} title="Open the full OpenJarvis app">Classic app</button>
        </div>
      </header>

      {life.error && <p className="zen-banner">Progress data unavailable: {life.error}</p>}

      <main className="zen-grid">
        <div className="zen-col zen-col--a">
          <ProfileCard summary={life.summary} nav={nav} active={section} onChanged={changed} />
          <KaizenCard summary={life.summary} />
          <JournalCard refreshKey={journalKey} onChanged={changed} />
        </div>
        <div className="zen-col zen-col--b">
          <ConsoleCard j={j} inputRef={inputRef} />
          <FocusCard summary={life.summary} onEnterFocus={() => setFocusOpen(true)} />
          <QuotesCard />
        </div>
        <div className="zen-col zen-col--c">
          <ProgressRingCard summary={life.summary} />
          <ScheduleCard summary={life.summary} routines={j.automations.items} onChanged={changed} onOpenRoutines={() => setDeckOpen(true)} />
          <StreakCard summary={life.summary} />
          <SystemCard j={j} onAction={onQuickAction} />
          <section className="zen-card zen-activity" aria-label="Activity">
            <span className="zen-eyebrow">Activity</span>
            <ol>
              {j.log.slice(-6).reverse().map((l) => (
                <li key={l.id} className={`lv-${l.level}`}><time>{l.time}</time><span>{l.text}</span></li>
              ))}
            </ol>
          </section>
        </div>
        <div className="zen-wide">
          <MissionCard summary={life.summary} onChanged={changed} />
          <ReminderCard />
        </div>
      </main>

      <ZenDock
        j={j}
        onHome={() => go('dashboard', 'zen-top')}
        onProgress={() => go('dashboard', 'zen-schedule')}
        onRoutines={() => setDeckOpen(true)}
        onFiles={() => setVaultOpen(true)}
        routineCount={activeRoutines}
      />

      {focusOpen && (
        <FocusOverlay
          onClose={() => setFocusOpen(false)}
          onLogged={(m) => { j.addLog(`Focus session logged: ${m} min`, 'ok'); changed(); }}
        />
      )}

      <ApprovalDock
        onNew={(a) => {
          j.addLog(`Approval needed: ${a.description}`, 'warn');
          j.announce(`approval-${a.id}`, 'Approval needed. Please approve or deny on screen.');
        }}
        onDecision={(a, approved) => j.addLog(`${approved ? 'Approved' : 'Denied'}: ${a.description}`, approved ? 'ok' : 'warn')}
      />
      <AttachmentsDeck
        open={vaultOpen}
        onClose={() => setVaultOpen(false)}
        onAttach={(a) => j.setPending((p) => (p.some((x) => x.id === a.id) ? p : [...p, a]))}
        onLog={j.addLog}
      />
      <AutomationsDeck
        open={deckOpen}
        onClose={() => setDeckOpen(false)}
        status={j.automations.status}
        items={j.automations.items}
        error={j.automations.error}
        refresh={j.automations.refresh}
        onLog={j.addLog}
      />
    </div>
  );
}
