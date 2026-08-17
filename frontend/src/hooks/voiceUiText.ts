import type { VoiceStatus } from '@/components/Visualizer/types';
import type { KioskState } from './useKioskState';
import type { LocalVoiceStatus } from './voiceStatus';
import type { UiLanguage } from './useUiLanguage';

interface VoiceUiCopy {
  language: {
    vietnamese: string;
    english: string;
  };
  languageHelper: string;
  voiceStatus: Record<LocalVoiceStatus, string>;
  kioskState: Record<KioskState, string>;
  panelStatus: Record<VoiceStatus, string>;
}

export const VOICE_UI_TEXT: Record<UiLanguage, VoiceUiCopy> = {
  vi: {
    language: { vietnamese: 'Tiếng Việt', english: 'English' },
    languageHelper: 'Ngôn ngữ cho lớp phủ Kiosk và trạng thái Voice.',
    voiceStatus: {
      idle: 'Jarvis đang chờ khách',
      connecting: 'Kết nối',
      listening: 'Lắng nghe',
      speaking: 'Nói',
      busy: 'Xử lý',
      processing: 'Xử lý',
      inference: 'Suy luận',
      tool: 'Tool',
      error: 'Đã xảy ra lỗi giọng nói',
      ended: 'Đã kết thúc',
    },
    kioskState: {
      idle: 'Jarvis đang chờ khách',
      approaching: 'Jarvis đang phát hiện có người',
      prompting: 'Jarvis đang chờ xác nhận',
      active: 'Jarvis đang trò chuyện',
      cleanup: 'Jarvis đang kết thúc phiên',
    },
    panelStatus: {
      idle: 'Sẵn sàng',
      listening: 'Đang lắng nghe',
      thinking: 'Đang xử lý',
      speaking: 'Đang nói',
    },
  },
  en: {
    language: { vietnamese: 'Vietnamese', english: 'English' },
    languageHelper: 'Language for Kiosk overlay and Voice status.',
    voiceStatus: {
      idle: 'Jarvis is idle waiting for a guest',
      connecting: 'Connecting',
      listening: 'Listening',
      speaking: 'Speaking',
      busy: 'Processing',
      processing: 'Processing',
      inference: 'Inference',
      tool: 'Tool',
      error: 'Voice error',
      ended: 'Voice ended',
    },
    kioskState: {
      idle: 'Jarvis is idle waiting for a guest',
      approaching: 'Jarvis is detecting someone',
      prompting: 'Jarvis is waiting for confirmation',
      active: 'Jarvis is in conversation',
      cleanup: 'Jarvis is wrapping up the session',
    },
    panelStatus: {
      idle: 'Ready',
      listening: 'Listening',
      thinking: 'Processing',
      speaking: 'Speaking',
    },
  },
};

export function voiceStatusLabel(
  language: UiLanguage,
  status: LocalVoiceStatus,
  detail: string | null = null,
): string {
  const label = VOICE_UI_TEXT[language].voiceStatus[status];
  if (!shouldShimmerVoiceStatus(status)) return label;
  return status === 'tool' && detail ? `${detail}...` : `${label}...`;
}

export function shouldShimmerVoiceStatus(status: LocalVoiceStatus): boolean {
  return status === 'connecting'
    || status === 'listening'
    || status === 'speaking'
    || status === 'processing'
    || status === 'inference'
    || status === 'tool'
    || status === 'busy';
}

export function kioskStateLabel(language: UiLanguage, state: KioskState): string {
  return VOICE_UI_TEXT[language].kioskState[state];
}

export function panelStatusLabel(language: UiLanguage, status: VoiceStatus): string {
  return VOICE_UI_TEXT[language].panelStatus[status];
}
