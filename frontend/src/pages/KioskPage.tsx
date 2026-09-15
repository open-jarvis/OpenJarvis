import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { X, ScreenShare, ScreenShareOff } from 'lucide-react';

import { AudioVisualizer } from '@/components/Visualizer/AudioVisualizer';
import { VisualizerControls } from '@/components/Visualizer/VisualizerControls';
import { FloatingCodexPet } from '@/components/Kiosk/Pet/FloatingCodexPet';
import { ScreenShareView } from '@/components/Kiosk/ScreenShareView';
import { currentVoiceTurnRows } from '@/components/Chat/voiceTurnRows';
import { useKioskState, type KioskState } from '@/hooks/useKioskState';
import { usePipecatVoiceMode } from '@/hooks/usePipecatVoiceMode';
import { useScreenShare } from '@/hooks/useScreenShare';
import { useUiLanguage } from '@/hooks/useUiLanguage';
import { shouldShimmerVoiceStatus, voiceStatusLabel } from '@/hooks/voiceUiText';
import { useAppStore } from '@/lib/store';
import {
  createKioskPresentationLifecycle,
  ensurePresentationSession,
  shouldEnsurePresentationSession,
} from '@/lib/kioskPresentation';
import { VISUALIZER_DEFAULTS } from '@/components/Visualizer/types';
import type { VisualizerSettings, VoiceStatus } from '@/components/Visualizer/types';
import type { LocalVoiceStatus } from '@/hooks/voiceStatus';
import { kioskVoiceCommand } from './kioskVoicePolicy';

const GLOW: Record<LocalVoiceStatus, string> = {
  idle: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(0,242,254,0.04) 0%, transparent 70%)',
  connecting: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(0,242,254,0.08) 0%, transparent 70%)',
  listening: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(0,255,100,0.08) 0%, transparent 70%)',
  speaking: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(79,172,254,0.10) 0%, transparent 70%)',
  busy: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(255,180,80,0.08) 0%, transparent 70%)',
  processing: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(0,242,254,0.08) 0%, transparent 70%)',
  inference: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(0,242,254,0.08) 0%, transparent 70%)',
  tool: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(0,242,254,0.08) 0%, transparent 70%)',
  error: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(255,80,80,0.10) 0%, transparent 70%)',
  ended: 'radial-gradient(ellipse 56% 56% at 50% 50%, rgba(0,242,254,0.04) 0%, transparent 70%)',
};

const STATUS_COLOR: Record<LocalVoiceStatus, string> = {
  idle: 'var(--color-text-secondary)',
  connecting: 'var(--color-accent)',
  listening: 'var(--color-success)',
  speaking: 'var(--color-accent)',
  busy: 'var(--color-warning)',
  processing: 'var(--color-accent)',
  inference: 'var(--color-accent)',
  tool: 'var(--color-accent)',
  error: 'var(--color-error)',
  ended: 'var(--color-text-secondary)',
};

export const VOICE_STATUS_GLOW_RGB: Record<LocalVoiceStatus, string> = {
  idle: '0, 242, 254',
  connecting: '0, 242, 254',
  listening: '0, 255, 100',
  speaking: '79, 172, 254',
  busy: '255, 180, 80',
  processing: '0, 242, 254',
  inference: '0, 242, 254',
  tool: '0, 242, 254',
  error: '255, 80, 80',
  ended: '79, 172, 254',
};

export const VOICE_STATUS_BASE_INTENSITY: Record<LocalVoiceStatus, number> = {
  idle: 0.2,
  connecting: 0.35,
  listening: 0.4,
  speaking: 0.4,
  busy: 0.35,
  processing: 0.35,
  inference: 0.35,
  tool: 0.35,
  error: 0.4,
  ended: 0.2,
};

export function computeEdgeGlowShadow(status: LocalVoiceStatus, glowValue: number): string {
  if (glowValue <= 0) return 'none';
  const rgb = VOICE_STATUS_GLOW_RGB[status] ?? '0, 242, 254';
  const base = VOICE_STATUS_BASE_INTENSITY[status] ?? 0.35;
  const intensity = (glowValue / 20) * base;
  const r = glowValue;

  // Soft, subtle ambient diffusion without harsh border lines
  const a1 = Math.min(1, 0.22 * intensity);
  const a2 = Math.min(1, 0.12 * intensity);
  const a3 = Math.min(1, 0.05 * intensity);

  return [
    `inset 0 0 ${Math.max(4, Math.round(r * 0.6))}px rgba(${rgb}, ${a1.toFixed(3)})`,
    `inset 0 0 ${Math.round(r * 1.8)}px ${Math.round(r * 0.1)}px rgba(${rgb}, ${a2.toFixed(3)})`,
    `inset 0 0 ${Math.round(r * 3.6)}px ${Math.round(r * 0.25)}px rgba(${rgb}, ${a3.toFixed(3)})`,
  ].join(', ');
}

const PANEL_STATUS: Record<LocalVoiceStatus, VoiceStatus> = {
  idle: 'idle', connecting: 'thinking', listening: 'listening', speaking: 'speaking',
  busy: 'thinking', error: 'idle', ended: 'idle',
  processing: 'thinking', inference: 'thinking', tool: 'thinking',
};

export function KioskPage() {
  const [settings, setSettings] = useState<VisualizerSettings>(() => {
    try {
      const storage = typeof window !== 'undefined' ? window.localStorage : globalThis.localStorage;
      if (storage) {
        const raw =
          storage.getItem('openjarvis_kiosk_visualizer_settings') ||
          storage.getItem('openjarvis_visualizer_settings');
        if (raw) return { ...VISUALIZER_DEFAULTS, ...JSON.parse(raw) };
      }
    } catch {}
    return VISUALIZER_DEFAULTS;
  });

  const handleSettingsChange = useCallback((next: VisualizerSettings) => {
    setSettings(next);
    try {
      const storage = typeof window !== 'undefined' ? window.localStorage : globalThis.localStorage;
      if (storage) {
        storage.setItem('openjarvis_kiosk_visualizer_settings', JSON.stringify(next));
        storage.setItem('openjarvis_visualizer_settings', JSON.stringify(next));
      }
    } catch {}
  }, []);

  const addMessage = useAppStore((state) => state.addMessage);
  const threadIdRef = useRef<string>('');
  const voice = usePipecatVoiceMode({
    onTurn: (message) => {
      if (threadIdRef.current) addMessage(threadIdRef.current, message);
    },
  });

  const edgeGlowShadow = useMemo(
    () => computeEdgeGlowShadow(voice.status, settings.glow),
    [voice.status, settings.glow]
  );
  const { state: kioskState, micEnabled, respond } = useKioskState();
  const share = useScreenShare();
  const { language: uiLanguage, setLanguage: setUiLanguage } = useUiLanguage();
  const navigate = useNavigate();
  const createConversation = useAppStore((state) => state.createConversation);
  const selectedModel = useAppStore((state) => state.selectedModel);
  const modelsLoading = useAppStore((state) => state.modelsLoading);
  const setVoiceSessionActive = useAppStore((state) => state.setVoiceSessionActive);
  const startedRef = useRef(false);
  const presentationLifecycleRef = useRef<ReturnType<typeof createKioskPresentationLifecycle> | null>(null);
  if (presentationLifecycleRef.current === null) {
    presentationLifecycleRef.current = createKioskPresentationLifecycle();
  }
  const presentationLifecycle = presentationLifecycleRef.current;
  const resetPresentation = presentationLifecycle.requestReset;
  const policyEpochRef = useRef(0);
  const micEnabledRef = useRef(micEnabled);

  micEnabledRef.current = micEnabled;

  useEffect(() => {
    setVoiceSessionActive(!['idle', 'ended', 'error', 'busy'].includes(voice.status));
    return () => setVoiceSessionActive(false);
  }, [setVoiceSessionActive, voice.status]);

  const ensurePresentation = useCallback(() => {
    void ensurePresentationSession(window.location.origin).then((sessionId) => {
      presentationLifecycle.setSessionId(sessionId);
    }).catch(() => {});
  }, [presentationLifecycle]);

  useEffect(() => {
    ensurePresentation();
  }, [ensurePresentation]);

  useEffect(() => {
    if (shouldEnsurePresentationSession(kioskState)) ensurePresentation();
  }, [ensurePresentation, kioskState]);

  useEffect(() => {
    const epoch = ++policyEpochRef.current;
    const command = kioskVoiceCommand({ micEnabled, voiceEnabled: voice.enabled, started: startedRef.current });

    if (command === 'unavailable') {
      return;
    }
    if (command === 'end') {
      startedRef.current = false;
      void presentationLifecycle.endVoiceThenReset(voice.end).catch(() => {});
      return;
    }
    if (command !== 'start' || modelsLoading || !selectedModel) return;

    const threadId = createConversation(selectedModel);
    threadIdRef.current = threadId;
    startedRef.current = true;
    presentationLifecycle.markActive(threadId);
    void voice.start(threadId, selectedModel).then(() => {
      if (epoch !== policyEpochRef.current || !micEnabledRef.current) {
        void presentationLifecycle.endVoiceThenReset(voice.end).catch(() => {});
      }
    }).catch(() => {});
  }, [createConversation, micEnabled, modelsLoading, presentationLifecycle, resetPresentation, selectedModel, voice.enabled, voice.end, voice.start]);

  useEffect(() => () => {
    if (startedRef.current) {
      startedRef.current = false;
      void presentationLifecycle.endVoiceThenReset(voice.end).catch(() => {});
    } else {
      resetPresentation();
    }
  }, [presentationLifecycle, resetPresentation, voice.end]);

  const rows = currentVoiceTurnRows({ ...voice, assistantText: voice.assistantCaptionText });
  const voiceStatusShimmers = shouldShimmerVoiceStatus(voice.status);

  return (
    <div className="relative flex-1 h-full overflow-hidden select-none" style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>
      {share.status === 'live' && (
        <ScreenShareView
          stream={share.stream}
          floating
          initialPlacement={settings.style === 'screen' ? 'center' : 'top-right'}
        />
      )}

      {/* Center ambient glow - intensity dynamically tuned by settings.glow */}
      <div
        aria-hidden
        data-testid="kiosk-center-glow"
        className="absolute inset-0 pointer-events-none transition-all duration-1000"
        style={{
          background: GLOW[voice.status],
          opacity: settings.glow > 0 ? Math.min(2.0, settings.glow / 20) : 0,
          zIndex: 0,
        }}
      />

      {/* 4-Edge ambient/border glow layer - color matching Voice state, spread/intensity driven by settings.glow */}
      <div
        aria-hidden
        data-testid="kiosk-edge-glow"
        className="absolute inset-0 pointer-events-none transition-all duration-700"
        style={{
          boxShadow: edgeGlowShadow,
          zIndex: 1,
        }}
      />

      {settings.style === '3d' && (
        <AudioVisualizer getFrequencyData={voice.getFrequencyData} settings={settings} />
      )}
      <VisualizerControls
        settings={settings}
        onSettingsChange={handleSettingsChange}
        status={PANEL_STATUS[voice.status]}
        uiLanguage={uiLanguage}
        onUiLanguageChange={setUiLanguage}
      />

      {settings.showPet && (
        <FloatingCodexPet
          initialPlacement="center"
          scale={settings.petScale}
          storageKey="openjarvis_kiosk_pet_pos_center"
          voiceStatus={voice.status}
          activityDetail={voice.activityDetail}
          assistantCaptionText={voice.assistantCaptionText}
        />
      )}

      {kioskState === 'prompting' && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div
            className="mx-4 max-w-sm rounded-2xl p-8 text-center shadow-2xl"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <div className="mb-4 text-4xl">🤖</div>
            <h2 className="mb-2 text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
              {uiLanguage === 'vi' ? 'Sẵn sàng trò chuyện?' : 'Ready to chat?'}
            </h2>
            <p className="mb-6 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {uiLanguage === 'vi'
                ? 'Cho phép trợ lý bật microphone để nhận yêu cầu của bạn.'
                : 'Allow the assistant to enable the microphone to hear your requests.'}
            </p>
            <div className="flex justify-center gap-3">
              <button
                onClick={() => void respond(true)}
                className="cursor-pointer rounded-xl bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-transform hover:scale-105"
              >
                {uiLanguage === 'vi' ? 'Bắt đầu trò chuyện' : 'Start chatting'}
              </button>
              <button
                onClick={() => void respond(false)}
                className="cursor-pointer rounded-xl px-6 py-2.5 text-sm font-semibold transition-transform hover:scale-105"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              >
                {uiLanguage === 'vi' ? 'Không phải bây giờ' : 'Not now'}
              </button>
            </div>
          </div>
        </div>
      )}

      <button
        onClick={() => navigate('/')}
        title="Exit kiosk"
        className="absolute top-4 right-4 z-30 w-9 h-9 rounded-full flex items-center justify-center cursor-pointer transition-colors hover:bg-[var(--color-bg-secondary)]"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-secondary)',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <X size={16} />
      </button>

      {!share.unavailable && (
        <button
          onClick={share.status === 'live' ? share.stop : share.start}
          title={share.status === 'live' ? 'Stop sharing' : 'Share Screen'}
          className="absolute top-4 left-4 z-30 h-9 px-3 rounded-full flex items-center gap-1.5 cursor-pointer transition-colors text-[12px] font-medium hover:bg-[var(--color-bg-secondary)]"
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-secondary)',
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          {share.status === 'live' ? <ScreenShareOff size={14} /> : <ScreenShare size={14} />}
          {share.status === 'live' ? 'Stop sharing' : 'Share Screen'}
        </button>
      )}

      {share.status === 'error' && share.error && (
        <div className="absolute top-16 left-4 z-30 px-3 py-2 rounded-xl text-[12px] max-w-[70%]" style={{ background: 'rgba(255,80,80,.12)', border: '1px solid rgba(255,80,80,.3)', color: '#ffb4b4' }}>
          {share.error}
        </div>
      )}

      {kioskState === 'active' && (
        <div className="absolute inset-x-0 bottom-0 z-20 flex flex-col items-center gap-3 px-4 pb-8 pointer-events-none">
          {settings.showCaptions && (
            <div className="w-full max-w-2xl flex flex-col items-center gap-2 text-center">
              {rows.filter((row) => row.role === 'user').map((row) => (
                <p
                  key={row.role}
                  className="text-[13px] leading-snug text-[var(--color-text-secondary)]"
                >
                  {row.text}
                </p>
              ))}
            </div>
          )}
          <div
            className="text-[13px] font-medium transition-all duration-500"
            style={{ color: STATUS_COLOR[voice.status] }}
          >
            <span
              className={voiceStatusShimmers ? 'text-shimmer' : undefined}
              style={voiceStatusShimmers ? {
                '--shimmer-base': STATUS_COLOR[voice.status],
                '--shimmer-highlight': 'var(--color-text)',
              } as React.CSSProperties : undefined}
            >
              {voiceStatusLabel(uiLanguage, voice.status, voice.activityDetail)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
