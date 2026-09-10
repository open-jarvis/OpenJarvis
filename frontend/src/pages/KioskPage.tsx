import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { X, ScreenShare, ScreenShareOff } from 'lucide-react';

import { AudioVisualizer } from '@/components/Visualizer/AudioVisualizer';
import { VisualizerControls } from '@/components/Visualizer/VisualizerControls';
import { KioskOverlay } from '@/components/Kiosk/KioskOverlay';
import { FloatingCodexPet } from '@/components/Kiosk/Pet/FloatingCodexPet';
import { ScreenShareView } from '@/components/Kiosk/ScreenShareView';
import { currentVoiceTurnRows } from '@/components/Chat/voiceTurnRows';
import { useKioskState, type KioskState } from '@/hooks/useKioskState';
import { usePipecatVoiceMode } from '@/hooks/usePipecatVoiceMode';
import { useScreenShare } from '@/hooks/useScreenShare';
import { useUiLanguage } from '@/hooks/useUiLanguage';
import { shouldShimmerVoiceStatus, voiceStatusLabel } from '@/hooks/voiceUiText';
import { useAppStore } from '@/lib/store';
import { createKioskPresentationLifecycle, ensurePresentationSession } from '@/lib/kioskPresentation';
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
  idle: 'rgba(255,255,255,0.45)', connecting: 'rgba(255,255,255,0.6)',
  listening: '#00ff64', speaking: '#4facfe', busy: '#ffb450',
  processing: '#00f2fe', inference: '#00f2fe', tool: '#00f2fe',
  error: '#ff8080', ended: 'rgba(255,255,255,0.45)',
};

const PANEL_STATUS: Record<LocalVoiceStatus, VoiceStatus> = {
  idle: 'idle', connecting: 'thinking', listening: 'listening', speaking: 'speaking',
  busy: 'thinking', error: 'idle', ended: 'idle',
  processing: 'thinking', inference: 'thinking', tool: 'thinking',
};

export function KioskPage() {
  const [settings, setSettings] = useState<VisualizerSettings>(VISUALIZER_DEFAULTS);
  const addMessage = useAppStore((state) => state.addMessage);
  const threadIdRef = useRef<string>('');
  const voice = usePipecatVoiceMode({
    onTurn: (message) => {
      if (threadIdRef.current) addMessage(threadIdRef.current, message);
    },
  });
  const { state: kioskState, micEnabled } = useKioskState();
  const share = useScreenShare();
  const { language: uiLanguage, setLanguage: setUiLanguage } = useUiLanguage();
  const navigate = useNavigate();
  const createConversation = useAppStore((state) => state.createConversation);
  const selectedModel = useAppStore((state) => state.selectedModel);
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
    void ensurePresentationSession(window.location.origin).then((sessionId) => {
      presentationLifecycle.setSessionId(sessionId);
    }).catch(() => {});
  }, [presentationLifecycle]);

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
    if (command !== 'start') return;

    const threadId = createConversation(selectedModel);
    threadIdRef.current = threadId;
    startedRef.current = true;
    presentationLifecycle.markActive(threadId);
    void voice.start(threadId, selectedModel).then(() => {
      if (epoch !== policyEpochRef.current || !micEnabledRef.current) {
        void presentationLifecycle.endVoiceThenReset(voice.end).catch(() => {});
      }
    }).catch(() => {});
  }, [createConversation, micEnabled, presentationLifecycle, resetPresentation, selectedModel, voice.enabled, voice.end, voice.start]);

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
    <div className="relative flex-1 h-full overflow-hidden select-none" style={{ background: '#06060f' }}>
      {share.status === 'live' && (
        <ScreenShareView
          stream={share.stream}
          floating
          initialPlacement={settings.style === 'screen' ? 'center' : 'top-right'}
        />
      )}

      <KioskOverlay showOverlay={settings.showOverlay} uiLanguage={uiLanguage} />
      <div aria-hidden className="absolute inset-0 pointer-events-none transition-all duration-1000" style={{ background: GLOW[voice.status], zIndex: 0 }} />
      {settings.style === '3d' && (
        <AudioVisualizer getFrequencyData={voice.getFrequencyData} settings={settings} />
      )}
      <VisualizerControls settings={settings} onSettingsChange={setSettings} status={PANEL_STATUS[voice.status]} uiLanguage={uiLanguage} onUiLanguageChange={setUiLanguage} />

      <FloatingCodexPet
        initialPlacement="center"
        scale={2.5}
        storageKey="openjarvis_kiosk_pet_pos_center"
        voiceStatus={voice.status}
        activityDetail={voice.activityDetail}
        assistantCaptionText={voice.assistantCaptionText}
      />

      <button onClick={() => navigate('/')} title="Exit kiosk" className="absolute top-4 right-4 z-30 w-9 h-9 rounded-full flex items-center justify-center cursor-pointer transition-colors" style={{ background: 'rgba(255,255,255,.06)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
        <X size={16} />
      </button>

      {!share.unavailable && (
        <button
          onClick={share.status === 'live' ? share.stop : share.start}
          title={share.status === 'live' ? 'Stop sharing' : 'Share Screen'}
          className="absolute top-4 left-4 z-30 h-9 px-3 rounded-full flex items-center gap-1.5 cursor-pointer transition-colors text-[12px] font-medium"
          style={{ background: 'rgba(255,255,255,.06)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
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
                  className="text-[13px] leading-snug text-[var(--color-text-tertiary)]"
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
                '--shimmer-highlight': '#ffffff',
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
