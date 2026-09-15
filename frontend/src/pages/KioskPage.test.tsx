import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { KioskPage, computeEdgeGlowShadow } from './KioskPage';
import type { LocalVoiceStatus } from '@/hooks/voiceStatus';
import type { ScreenShareStatus } from '@/hooks/useScreenShare';

const storageMap = new Map<string, string>();
let mockUiLanguage = 'vi';

let mockVoiceState = {
  enabled: true,
  status: 'idle' as LocalVoiceStatus,
  activityDetail: null as string | null,
  assistantCaptionText: '',
  getFrequencyData: () => new Uint8Array(),
  start: vi.fn().mockResolvedValue(undefined),
  end: vi.fn().mockResolvedValue(undefined),
};

let mockScreenShare = {
  unavailable: false,
  status: 'idle' as ScreenShareStatus,
  stream: null as MediaStream | null,
  error: null as string | null,
  start: vi.fn().mockResolvedValue(undefined),
  stop: vi.fn(),
};

const mockCreateConversation = vi.fn(() => 'thread-123');
const mockAddMessage = vi.fn();
const mockSetVoiceSessionActive = vi.fn();

const mockLifecycle = {
  requestReset: vi.fn(),
  setSessionId: vi.fn(),
  endVoiceThenReset: vi.fn().mockResolvedValue(undefined),
  markActive: vi.fn(),
};

let latestHeroProps: {
  onStartVoice: () => void;
  onStartScreenShare: () => void;
  isVoiceActive?: boolean;
} | null = null;

let latestDockProps: {
  voiceStatus: LocalVoiceStatus;
  isVoiceActive: boolean;
  shareStatus: ScreenShareStatus;
  onToggleVoice: () => void;
  onToggleScreenShare: () => void;
} | null = null;

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

  mockScreenShare = {
    unavailable: false,
    status: 'idle',
    stream: null,
    error: null,
    start: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn(),
  };

  mockVoiceState = {
    enabled: true,
    status: 'idle',
    activityDetail: null,
    assistantCaptionText: '',
    getFrequencyData: () => new Uint8Array(),
    start: vi.fn().mockResolvedValue(undefined),
    end: vi.fn().mockResolvedValue(undefined),
  };

  latestHeroProps = null;
  latestDockProps = null;
  mockCreateConversation.mockClear();
  mockLifecycle.markActive.mockClear();
  mockLifecycle.endVoiceThenReset.mockClear();
});

vi.mock('@/hooks/useKioskState', () => ({
  useKioskState: () => ({ state: 'prompting', micEnabled: false, respond: vi.fn() }),
}));
vi.mock('@/hooks/usePipecatVoiceMode', () => ({
  usePipecatVoiceMode: () => mockVoiceState,
}));
vi.mock('@/hooks/useScreenShare', () => ({
  useScreenShare: () => mockScreenShare,
}));
vi.mock('@/hooks/useUiLanguage', () => ({
  useUiLanguage: () => ({ language: mockUiLanguage, setLanguage: (l: string) => { mockUiLanguage = l; } }),
}));
vi.mock('@/lib/store', () => ({
  useAppStore: (selector: (state: Record<string, unknown>) => unknown) => selector({
    addMessage: mockAddMessage,
    createConversation: mockCreateConversation,
    selectedModel: 'gpt-5.6-luna',
    modelsLoading: false,
    setVoiceSessionActive: mockSetVoiceSessionActive,
  }),
}));
vi.mock('@/lib/kioskPresentation', () => ({
  createKioskPresentationLifecycle: () => mockLifecycle,
  ensurePresentationSession: vi.fn(),
  shouldEnsurePresentationSession: vi.fn(() => false),
}));
vi.mock('@/components/Visualizer/AudioVisualizer', () => ({
  AudioVisualizer: () => <div data-testid="mock-audio-visualizer" />,
}));
vi.mock('@/components/Visualizer/VisualizerControls', () => ({ VisualizerControls: () => null }));
vi.mock('@/components/Kiosk/Pet/FloatingCodexPet', () => ({
  FloatingCodexPet: (props: { scale?: number }) => (
    <div data-testid="mock-floating-codex-pet" data-scale={props.scale} />
  ),
}));
vi.mock('@/components/Chat/voiceTurnRows', () => ({ currentVoiceTurnRows: () => [] }));

vi.mock('@/components/Kiosk/ScreenShareHero', () => ({
  ScreenShareHero: (props: {
    onStartVoice: () => void;
    onStartScreenShare: () => void;
    isVoiceActive?: boolean;
  }) => {
    latestHeroProps = props;
    return (
      <div data-testid="screen-share-hero">
        <button data-testid="hero-talk-btn" onClick={props.onStartVoice}>Talk</button>
        <button data-testid="hero-share-btn" onClick={props.onStartScreenShare}>Share Screen</button>
      </div>
    );
  },
}));

vi.mock('@/components/Kiosk/ScreenShareDock', () => ({
  ScreenShareDock: (props: {
    voiceStatus: LocalVoiceStatus;
    isVoiceActive: boolean;
    shareStatus: ScreenShareStatus;
    onToggleVoice: () => void;
    onToggleScreenShare: () => void;
  }) => {
    latestDockProps = props;
    return (
      <div data-testid="screen-share-dock">
        <button data-testid="dock-mic-btn" onClick={props.onToggleVoice}>Mic</button>
        <button data-testid="dock-share-btn" onClick={props.onToggleScreenShare}>Share</button>
      </div>
    );
  },
}));

vi.mock('@/components/Kiosk/ScreenShareView', () => ({
  ScreenShareView: (props: {
    floating?: boolean;
    initialPlacement?: 'top-right' | 'center';
  }) => (
    <div
      data-testid="mock-screen-share-view"
      data-floating={props.floating ? 'true' : 'false'}
      data-placement={props.initialPlacement}
    />
  ),
}));

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

  describe('ScreenShare Hero and Dock integration', () => {
    it('renders ScreenShareHero and ScreenShareDock when settings.style is screen and share is not live', () => {
      mockScreenShare.status = 'idle';
      const markup = renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      expect(markup).toContain('data-testid="screen-share-hero"');
      expect(markup).toContain('data-testid="screen-share-dock"');
      expect(markup).not.toContain('data-testid="mock-screen-share-view"');
    });

    it('hides top-left redundant screen share button when settings.style is screen', () => {
      mockScreenShare.unavailable = false;
      const markup = renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      expect(markup).not.toContain('title="Share Screen"');
      expect(markup).not.toContain('title="Stop sharing"');
    });

    it('renders ScreenShareView and ScreenShareDock (but hides hero) when share.status is live', () => {
      mockScreenShare.status = 'live';
      const markup = renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      expect(markup).toContain('data-testid="mock-screen-share-view"');
      expect(markup).toContain('data-placement="center"');
      expect(markup).toContain('data-testid="screen-share-dock"');
      expect(markup).not.toContain('data-testid="screen-share-hero"');
    });

    it('does not render ScreenShareHero or ScreenShareDock when settings.style is 3d', () => {
      localStorage.setItem(
        'openjarvis_kiosk_visualizer_settings',
        JSON.stringify({ style: '3d' }),
      );

      const markup = renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      expect(markup).toContain('data-testid="mock-audio-visualizer"');
      expect(markup).not.toContain('data-testid="screen-share-hero"');
      expect(markup).not.toContain('data-testid="screen-share-dock"');
      expect(markup).toContain('title="Share Screen"');
    });

    it('triggers voice start when onStartVoice is called in ScreenShareHero', () => {
      renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      expect(latestHeroProps).not.toBeNull();
      latestHeroProps!.onStartVoice();

      expect(mockCreateConversation).toHaveBeenCalledWith('gpt-5.6-luna');
      expect(mockLifecycle.markActive).toHaveBeenCalledWith('thread-123');
      expect(mockVoiceState.start).toHaveBeenCalledWith('thread-123', 'gpt-5.6-luna');
    });

    it('toggles voice on and off via ScreenShareDock', () => {
      renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      expect(latestDockProps).not.toBeNull();

      // When voice is inactive, toggle starts voice
      latestDockProps!.onToggleVoice();
      expect(mockVoiceState.start).toHaveBeenCalledWith('thread-123', 'gpt-5.6-luna');

      // Re-render with speaking voice status
      mockVoiceState.status = 'speaking';
      renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      latestDockProps!.onToggleVoice();
      expect(mockLifecycle.endVoiceThenReset).toHaveBeenCalledWith(mockVoiceState.end);
    });

    it('toggles screen share via ScreenShareDock', () => {
      mockScreenShare.status = 'idle';
      renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      expect(latestDockProps).not.toBeNull();
      latestDockProps!.onToggleScreenShare();
      expect(mockScreenShare.start).toHaveBeenCalledTimes(1);

      // When live, toggle calls stop
      mockScreenShare.status = 'live';
      renderToStaticMarkup(
        <MemoryRouter>
          <KioskPage />
        </MemoryRouter>,
      );

      latestDockProps!.onToggleScreenShare();
      expect(mockScreenShare.stop).toHaveBeenCalledTimes(1);
    });
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
