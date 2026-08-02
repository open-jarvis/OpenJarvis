import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { VoiceProfileInfo } from '../../lib/api';
import { VoiceProfileCard } from './VoiceAuditionPanel';

const profile: VoiceProfileInfo = {
  voice_id: 'jarvis-deep-calm',
  number: 1,
  label: 'Tief und ruhig',
  backend: 'chatterbox',
  pitch_semitones: 0,
  speed: 1,
  exaggeration: 0.38,
  cfg_weight: 0.52,
  temperature: 0.72,
  seed: 104729,
  description: 'Ruhiges neuronales Stimmprofil mit eigenem natürlichem Timbre.',
  audition_ready: true,
};

describe('Voice audition UI', () => {
  it('shows the numbered profile, settings, player, and persistent selection state', () => {
    const html = renderToStaticMarkup(
      <VoiceProfileCard
        profile={profile}
        audioUrl="blob:jarvis-deep-calm"
        selected
        busy={false}
        onSelect={vi.fn()}
      />,
    );

    expect(html).toContain('1. Tief und ruhig');
    expect(html).toContain('eigenes neuronales Timbre');
    expect(html).toContain('1.00×');
    expect(html).toContain('104729');
    expect(html).toContain('blob:jarvis-deep-calm');
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('Als JARVIS-Stimme ausgewählt');
  });

  it('labels the CPU fallback without pretending it has Chatterbox controls', () => {
    const html = renderToStaticMarkup(
      <VoiceProfileCard
        profile={{
          ...profile,
          voice_id: 'jarvis-piper-fast',
          number: 4,
          label: 'Notfallstimme (schnell)',
          backend: 'piper',
          exaggeration: 0,
          cfg_weight: 0,
        }}
        selected={false}
        busy={false}
        onSelect={vi.fn()}
      />,
    );

    expect(html).toContain('4. Notfallstimme (schnell)');
    expect(html).toContain('CPU-Notfallprofil');
    expect(html).toContain('kontrolliert');
    expect(html).toContain('n/a');
    expect(html).toContain('Probe wurde noch nicht erzeugt.');
    expect(html).toContain('Als JARVIS-Stimme verwenden');
  });
});
