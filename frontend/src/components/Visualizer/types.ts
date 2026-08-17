/** idle → listening (mic) → thinking (STT+LLM+TTS) → speaking (playback) → idle */
export type VoiceStatus = 'idle' | 'listening' | 'thinking' | 'speaking';
export type VoiceLang = 'vi' | 'en';

export type VisualizerStyle = 'wave' | '3d';
export type VisualizerTheme = 'gold' | 'cyan' | 'cyber' | 'aurora' | 'sunset';

export interface VisualizerSettings {
  style: VisualizerStyle;
  theme: VisualizerTheme;
  size: number;
  gain: number;
  speed: number;
  glow: number;
  showCaptions: boolean;
  showOverlay: boolean;
}

export const VISUALIZER_DEFAULTS: VisualizerSettings = {
  style: '3d',
  theme: 'gold',
  size: 150,
  gain: 1.4,
  speed: 1.0,
  glow: 20,
  showCaptions: true,
  showOverlay: true,
};
