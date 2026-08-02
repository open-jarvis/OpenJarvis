import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CanonicalTaskEvent } from '../../../lib/api';
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

function experience(mode: 'talk' | 'text') {
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
      approvals={[]}
      decisionBusy={null}
      onPreferencesChange={() => {}}
      onDraftChange={() => {}}
      onSubmit={() => {}}
      onToggleMicrophone={() => {}}
      onStop={() => {}}
      onNewConversation={() => {}}
      onLanguageChange={() => {}}
      onApprovalDecision={() => {}}
    />,
  );
}

afterEach(() => vi.useRealTimers());

describe('Jarvis experience', () => {
  it('keeps the approved avatar asset byte-identical', () => {
    const bytes = readFileSync(resolve(process.cwd(), 'public/assets/jarvis/cosmic-face.png'));
    expect(createHash('sha256').update(bytes).digest('hex').toUpperCase()).toBe(
      'BE9B0A872B6A853D178B3D56465C881DE4EA2070E034B5E8AFE2CFFBF2A84C1B',
    );
  });

  it('shows the avatar but no chat or internal work in Talk mode', () => {
    const html = experience('talk');
    expect(html).toContain('Jarvis Talk-Modus');
    expect(html).toContain('/assets/jarvis/cosmic-face.png');
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
    expect(settings).toContain('Mundbewegung');
    expect(settings).toContain('<option value="off" selected="">Aus</option>');
    expect(settings).toContain('Reduzierte Bewegung');
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
    expect(userSafeError('Traceback with token and raw JSON')).toBe('Jarvis konnte die Aktion nicht abschließen. Versuche es bitte erneut.');
  });
});
