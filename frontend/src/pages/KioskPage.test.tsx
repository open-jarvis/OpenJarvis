import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { KioskPage, computeEdgeGlowShadow, VOICE_STATUS_GLOW_RGB } from './KioskPage';

const storageMap = new Map<string, string>();
beforeEach(() => {
  storageMap.clear();
  globalThis.localStorage = {
    getItem: (k: string) => storageMap.get(k) ?? null,
    setItem: (k: string, v: string) => { storageMap.set(k, String(v)); },
    removeItem: (k: string) => { storageMap.delete(k); },
    clear: () => { storageMap.clear(); },
    key: (i: number) => Array.from(storageMap.keys())[i] ?? null,
    length: storageMap.size,
  } as unknown as Storage;
});

vi.mock('@/hooks/useKioskState', () => ({
  useKioskState: () => ({ state: 'prompting', micEnabled: false, respond: vi.fn() }),
}));
vi.mock('@/hooks/usePipecatVoiceMode', () => ({
  usePipecatVoiceMode: () => ({ enabled: true, status: 'idle', assistantCaptionText: '', getFrequencyData: () => new Uint8Array() }),
}));
vi.mock('@/hooks/useScreenShare', () => ({ useScreenShare: () => ({ unavailable: true, status: 'idle' }) }));
let mockUiLanguage = 'vi';
vi.mock('@/hooks/useUiLanguage', () => ({
  useUiLanguage: () => ({ language: mockUiLanguage, setLanguage: (l: string) => { mockUiLanguage = l; } }),
}));
vi.mock('@/lib/store', () => ({
  useAppStore: (selector: (state: Record<string, unknown>) => unknown) => selector({
    addMessage: vi.fn(), createConversation: vi.fn(), selectedModel: 'gpt-5.6-luna',
    modelsLoading: false, setVoiceSessionActive: vi.fn(),
  }),
}));
vi.mock('@/lib/kioskPresentation', () => ({
  createKioskPresentationLifecycle: () => ({ requestReset: vi.fn(), setSessionId: vi.fn(), endVoiceThenReset: vi.fn(), markActive: vi.fn() }),
  ensurePresentationSession: vi.fn(),
  shouldEnsurePresentationSession: vi.fn(() => false),
}));
vi.mock('@/components/Visualizer/AudioVisualizer', () => ({ AudioVisualizer: () => null }));
vi.mock('@/components/Visualizer/VisualizerControls', () => ({ VisualizerControls: () => null }));
vi.mock('@/components/Kiosk/Pet/FloatingCodexPet', () => ({
  FloatingCodexPet: (props: { scale?: number }) => (
    <div data-testid="mock-floating-codex-pet" data-scale={props.scale} />
  ),
}));
vi.mock('@/components/Chat/voiceTurnRows', () => ({ currentVoiceTurnRows: () => [] }));

describe('KioskPage', () => {
  it('renders consent actions in Vietnamese when uiLanguage is vi', () => {
    mockUiLanguage = 'vi';
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <KioskPage />
      </MemoryRouter>,
    );

    expect(markup).toContain('Sẵn sàng trò chuyện?');
    expect(markup).toContain('Bắt đầu trò chuyện');
    expect(markup).toContain('Không phải bây giờ');
    expect(markup).toContain('Cho phép trợ lý bật microphone để nhận yêu cầu của bạn.');
    expect(markup).not.toContain('Ready to chat?');
    expect(markup).not.toContain('Start chatting');
  });

  it('renders consent actions in English when uiLanguage is en', () => {
    mockUiLanguage = 'en';
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <KioskPage />
      </MemoryRouter>,
    );

    expect(markup).toContain('Ready to chat?');
    expect(markup).toContain('Start chatting');
    expect(markup).toContain('Not now');
    expect(markup).toContain('Allow the assistant to enable the microphone to hear your requests.');
    expect(markup).not.toContain('Sẵn sàng trò chuyện?');
    expect(markup).not.toContain('Bắt đầu trò chuyện');
  });

  it('renders 4-edge border glow and center ambient glow layers', () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <KioskPage />
      </MemoryRouter>,
    );

    expect(markup).toContain('data-testid="kiosk-edge-glow"');
    expect(markup).toContain('data-testid="kiosk-center-glow"');
  });

  it('renders mascot pet with default petScale when showPet is true', () => {
    localStorage.removeItem('openjarvis_kiosk_visualizer_settings');
    localStorage.removeItem('openjarvis_visualizer_settings');

    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <KioskPage />
      </MemoryRouter>,
    );

    expect(markup).toContain('data-testid="mock-floating-codex-pet"');
    expect(markup).toContain('data-scale="2.5"');
  });

  it('hides mascot pet when showPet is false in localStorage', () => {
    localStorage.setItem(
      'openjarvis_kiosk_visualizer_settings',
      JSON.stringify({ showPet: false, petScale: 3.0 }),
    );

    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <KioskPage />
      </MemoryRouter>,
    );

    expect(markup).not.toContain('data-testid="mock-floating-codex-pet"');
    localStorage.removeItem('openjarvis_kiosk_visualizer_settings');
  });

  it('supports legacy openjarvis_visualizer_settings key with custom petScale', () => {
    localStorage.removeItem('openjarvis_kiosk_visualizer_settings');
    localStorage.setItem(
      'openjarvis_visualizer_settings',
      JSON.stringify({ showPet: true, petScale: 3.5 }),
    );

    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <KioskPage />
      </MemoryRouter>,
    );

    expect(markup).toContain('data-testid="mock-floating-codex-pet"');
    expect(markup).toContain('data-scale="3.5"');
    localStorage.removeItem('openjarvis_visualizer_settings');
  });

  describe('computeEdgeGlowShadow', () => {
    it('returns "none" when glowValue is 0 or negative', () => {
      expect(computeEdgeGlowShadow('speaking', 0)).toBe('none');
      expect(computeEdgeGlowShadow('listening', -5)).toBe('none');
    });

    it('contains the correct RGB color for speaking (blue) and listening (green)', () => {
      const speakingShadow = computeEdgeGlowShadow('speaking', 20);
      expect(speakingShadow).toContain('rgba(79, 172, 254');
      // No harsh solid 1px border line
      expect(speakingShadow).not.toContain('inset 0 0 0 1px');

      const listeningShadow = computeEdgeGlowShadow('listening', 20);
      expect(listeningShadow).toContain('rgba(0, 255, 100');

      const errorShadow = computeEdgeGlowShadow('error', 20);
      expect(errorShadow).toContain('rgba(255, 80, 80');
    });

    it('scales spread and intensity with glow slider value', () => {
      const defaultGlow = computeEdgeGlowShadow('speaking', 20);
      const highGlow = computeEdgeGlowShadow('speaking', 50);

      expect(defaultGlow).toContain('inset 0 0 12px');
      expect(highGlow).toContain('inset 0 0 30px');
    });
  });
});
