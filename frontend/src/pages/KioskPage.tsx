import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { X } from 'lucide-react';

import { AudioVisualizer } from '@/components/Visualizer/AudioVisualizer';
import { VisualizerControls } from '@/components/Visualizer/VisualizerControls';
import { KioskOverlay } from '@/components/Kiosk/KioskOverlay';
import { currentVoiceTurnRows } from '@/components/Chat/voiceTurnRows';
import { useKioskState, type KioskState } from '@/hooks/useKioskState';
import { usePipecatVoiceMode } from '@/hooks/usePipecatVoiceMode';
import { useUiLanguage } from '@/hooks/useUiLanguage';
import { shouldShimmerVoiceStatus, voiceStatusLabel } from '@/hooks/voiceUiText';
import { useAppStore } from '@/lib/store';
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
  const { language: uiLanguage, setLanguage: setUiLanguage } = useUiLanguage();
  const navigate = useNavigate();
  const createConversation = useAppStore((state) => state.createConversation);
  const selectedModel = useAppStore((state) => state.selectedModel);
  const startedRef = useRef(false);
  const policyEpochRef = useRef(0);
  const micEnabledRef = useRef(micEnabled);

  micEnabledRef.current = micEnabled;

  useEffect(() => {
    const epoch = ++policyEpochRef.current;
    const command = kioskVoiceCommand({ micEnabled, voiceEnabled: voice.enabled, started: startedRef.current });

    if (command === 'unavailable') {
      return;
    }
    if (command === 'end') {
      startedRef.current = false;
      void voice.end();
      return;
    }
    if (command !== 'start') return;

    const threadId = createConversation(selectedModel);
    threadIdRef.current = threadId;
    startedRef.current = true;
    void voice.start(threadId, selectedModel).then(() => {
      if (epoch !== policyEpochRef.current || !micEnabledRef.current) void voice.end();
    }).catch(() => {});
  }, [createConversation, micEnabled, selectedModel, voice.enabled, voice.end, voice.start]);

  useEffect(() => () => {
    if (startedRef.current) {
      startedRef.current = false;
      void voice.end();
    }
  }, [voice.end]);

  const rows = currentVoiceTurnRows({ ...voice, assistantText: voice.assistantCaptionText });
  const voiceStatusShimmers = shouldShimmerVoiceStatus(voice.status);

  return (
    <div className="relative flex-1 h-full overflow-hidden select-none" style={{ background: '#06060f' }}>
      <KioskOverlay showOverlay={settings.showOverlay} uiLanguage={uiLanguage} />
      <div aria-hidden className="absolute inset-0 pointer-events-none transition-all duration-1000" style={{ background: GLOW[voice.status], zIndex: 0 }} />
      <AudioVisualizer getFrequencyData={voice.getFrequencyData} settings={settings} />
      <VisualizerControls settings={settings} onSettingsChange={setSettings} status={PANEL_STATUS[voice.status]} uiLanguage={uiLanguage} onUiLanguageChange={setUiLanguage} />

      <button onClick={() => navigate('/')} title="Exit kiosk" className="absolute top-4 right-4 z-30 w-9 h-9 rounded-full flex items-center justify-center cursor-pointer transition-colors" style={{ background: 'rgba(255,255,255,.06)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
        <X size={16} />
      </button>

      {voice.error && kioskState === 'active' && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-30 px-4 py-2.5 rounded-xl text-[12px] max-w-[90%]" style={{ background: 'rgba(255,80,80,.12)', border: '1px solid rgba(255,80,80,.3)', color: '#ffb4b4' }}>
          {voice.error}
        </div>
      )}

      {kioskState === 'active' && (
        <div className="absolute inset-x-0 bottom-0 z-20 flex flex-col items-center gap-3 px-4 pb-8 pointer-events-none">
          {settings.showCaptions && (
            <div className="w-full max-w-2xl flex flex-col items-center gap-2 text-center">
              {rows.map((row) => <p key={row.role} className={row.role === 'assistant' ? 'text-[15px] leading-relaxed max-w-full' : 'text-[13px] leading-snug'} style={{ color: row.role === 'error' ? '#ffb4b4' : row.role === 'assistant' ? 'var(--color-text)' : 'var(--color-text-tertiary)' }}>{row.text}</p>)}
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
