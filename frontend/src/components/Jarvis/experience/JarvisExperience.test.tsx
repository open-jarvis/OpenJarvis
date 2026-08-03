import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CanonicalTaskEvent, FlowStatus } from '../../../lib/api';
import { DEFAULT_JARVIS_PREFERENCES } from './preferences';
import {
  JarvisExperience,
  MenuPanel,
  SettingsPanel,
  userSafeError,
  visibleConversation,
} from './JarvisExperience';
import { DEFAULT_VOICE_SNAPSHOT, deriveVoiceSnapshot, MockVoiceAdapter } from './voiceAdapter';
import { resolveAnimationTier } from './useAnimationBudget';

function event(eventType: string, content: string, sequence: number): CanonicalTaskEvent {
  return {
    event_id: `event-${sequence}`,
    task_id: 'task-1',
    sequence,
    event_type: eventType,
    occurred_at: '2026-08-02T00:00:00Z',
    cause: 'test',
    component: 'test',
    status_from: null,
    status_to: null,
    thread_id: null,
    item_id: null,
    approval_id: null,
    artifact_id: null,
    payload: { content },
  };
}

const timeline = [
  event('chat.user_message', 'Zeige mir den Status.', 1),
  event('tool.output', 'C:\\private\\internal.json', 2),
  event('chat.assistant_message', 'Fertig.\n\n```ts\nconst ready = true;\n```\n\n| Zustand | Wert |\n|---|---|\n| Bereit | Ja |', 3),
  event('agent.plan', 'Verborgener interner Plan', 4),
];

function experience(mode: 'talk' | 'text', flowStatus: FlowStatus | null = null) {
  return renderToStaticMarkup(
    <JarvisExperience
      sessionId="session-test"
      timeline={timeline}
      activeTaskStatus={null}
      draft=""
      sending={false}
      submitBlocked={false}
      error={null}
      voice={{ ...DEFAULT_VOICE_SNAPSHOT, updatedAt: 1 }}
      sttAvailable
      ttsAvailable
      speechLanguage="de-DE"
      preferences={{ ...DEFAULT_JARVIS_PREFERENCES, mode }}
      actions={[]}
      flowStatus={flowStatus}
      flowBusy={false}
      audioBackendInfo={{ backend: null, fallbackUsed: false, cacheHit: false, chunksSkipped: 0, lastError: null }}
      onPreferencesChange={() => {}}
      onDraftChange={() => {}}
      onSubmit={() => {}}
      onToggleMicrophone={() => {}}
      onStop={() => {}}
      onNewConversation={() => {}}
      onLanguageChange={() => {}}
      onAccessModeChange={() => {}}
    />,
  );
}

afterEach(() => vi.useRealTimers());

describe('Jarvis experience', () => {
  it('uses the responsive star core without portrait or mouth selectors', () => {
    const css = readFileSync(
      resolve(process.cwd(), 'src/components/Jarvis/experience/jarvis-experience.css'),
      'utf8',
    );
    expect(css).toContain('.jarvis-core__sphere');
    expect(css).toContain('.jarvis-core__field');
    expect(css).not.toContain('jarvis-avatar__portrait');
    expect(css).not.toContain('jarvis-avatar__mouth');
  });

  it('shows the star core but no chat or internal work in Talk mode', () => {
    const html = experience('talk');
    expect(html).toContain('Jarvis Talk-Modus');
    expect(html).toContain('jarvis-core__sphere');
    expect(html).not.toContain('<img');
    expect(html).toContain('data-voice-state="idle"');
    expect(html).not.toContain('Zeige mir den Status');
    expect(html).not.toContain('Fertig.');
    expect(html).not.toContain('private');
    expect(html).not.toContain('Verborgener interner Plan');
    expect(html).not.toContain('Task timeline');
  });

  it('renders only user and final assistant messages in Text mode', () => {
    const html = experience('text');
    expect(html).toContain('Jarvis Text-Modus');
    expect(html).toContain('Zeige mir den Status');
    expect(html).toContain('const ready = true;');
    expect(html).toContain('<table>');
    expect(html).not.toContain('private');
    expect(html).not.toContain('Verborgener interner Plan');
    expect(visibleConversation(timeline)).toHaveLength(2);
  });

  it('shows an authenticated Flow grant without legacy approval controls', () => {
    const html = experience('text', {
      mode: 'flow',
      owner_authenticated: true,
      session_id: 'flow-session-test',
      activated_at: '2026-08-03T14:00:00Z',
      expires_at: '2026-08-03T22:00:00Z',
      last_activity_at: '2026-08-03T14:01:00Z',
      remaining_seconds: 28_740,
      capabilities: {
        filesystem: 'full_machine',
        desktop: 'full',
        browser: 'full',
      },
      lock_reason: '',
    });

    expect(html).toContain('FLOW-MODUS AKTIV');
    expect(html).toContain('7h 59m verbleibend');
    expect(html).toContain('Sperren');
    expect(html).toContain('Assistant');
    expect(html).not.toContain('Allow once');
    expect(html).not.toContain('Pending approval');
  });

  it('does not persist Flow grants in browser storage code', () => {
    const apiSource = readFileSync(resolve(process.cwd(), 'src/lib/api.ts'), 'utf8');
    const workspaceStore = readFileSync(resolve(process.cwd(), 'src/lib/jarvisStore.ts'), 'utf8');

    expect(apiSource).not.toMatch(/localStorage.{0,80}(flow|grant)/i);
    expect(workspaceStore).not.toMatch(/flow(Status|Grant|Session)/);
  });

  it('exposes a closed, keyboard-labelled menu and real settings controls', () => {
    const menu = renderToStaticMarkup(
      <MenuPanel
        open
        mode="talk"
        developerMode
        onClose={() => {}}
        onModeChange={() => {}}
        onNewConversation={() => {}}
        onOpenSettings={() => {}}
        onOpenDeveloper={() => {}}
      />,
    );
    const settings = renderToStaticMarkup(
      <SettingsPanel
        open
        preferences={DEFAULT_JARVIS_PREFERENCES}
        sttAvailable
        ttsAvailable
        language="de-DE"
        onClose={() => {}}
        onChange={() => {}}
        onLanguageChange={() => {}}
      />,
    );
    expect(menu).toContain('aria-modal="true"');
    expect(menu).toContain('Neue Unterhaltung');
    expect(menu).toContain('Talk-Modus');
    expect(menu).toContain('Text-Modus');
    expect(settings).toContain('Sternkern im Textmodus');
    expect(settings).toContain('<option value="standard" selected="">Standard</option>');
    expect(settings).toContain('Reduzierte Bewegung');
    expect(settings).toContain('Stimmenauswahl');
  });

  it('maps production state without starting another voice implementation', () => {
    expect(deriveVoiceSnapshot({
      recording: true,
      processing: false,
      speaking: false,
      sttAvailable: true,
      streamStatus: 'live',
    }).state).toBe('listening');
    expect(deriveVoiceSnapshot({
      recording: false,
      processing: false,
      speaking: true,
      sttAvailable: true,
      streamStatus: 'live',
      volumeLevel: 4,
    }).volumeLevel).toBe(1);
    expect(deriveVoiceSnapshot({
      recording: false,
      processing: false,
      speaking: false,
      sttAvailable: false,
      streamStatus: 'offline',
    }).state).toBe('offline');
  });

  it('simulates speaking levels only inside the development mock', () => {
    vi.useFakeTimers();
    const adapter = new MockVoiceAdapter();
    adapter.setState('speaking');
    vi.advanceTimersByTime(100);
    expect(adapter.getSnapshot().state).toBe('speaking');
    expect(adapter.getSnapshot().volumeLevel).toBeGreaterThan(0);
    adapter.interruptSpeech();
    expect(adapter.getSnapshot().playbackState).toBe('interrupted');
    expect(vi.getTimerCount()).toBe(0);
    adapter.dispose();
  });

  it('uses bounded animation fallbacks for low FPS, background, and reduced motion', () => {
    expect(resolveAnimationTier({ quality: 'standard', reducedMotion: false, pageVisible: true, fps: 60 })).toBe(1);
    expect(resolveAnimationTier({ quality: 'standard', reducedMotion: false, pageVisible: true, fps: 42 })).toBe(2);
    expect(resolveAnimationTier({ quality: 'standard', reducedMotion: false, pageVisible: true, fps: 24 })).toBe(3);
    expect(resolveAnimationTier({ quality: 'high', reducedMotion: false, pageVisible: false, fps: 60 })).toBe(4);
    expect(resolveAnimationTier({ quality: 'high', reducedMotion: true, pageVisible: true, fps: 60 })).toBe(4);
  });

  it('redacts technical errors from the normal UI', () => {
    expect(userSafeError('Server failed at C:\\private\\app.py')).toBe('Die Verbindung zu Jarvis ist unterbrochen. Die Wiederherstellung läuft.');
    expect(userSafeError('Traceback with token and raw JSON')).toBe('Die Aktion ist fehlgeschlagen. Im Statusbereich stehen weitere sichere Details.');
  });
});
