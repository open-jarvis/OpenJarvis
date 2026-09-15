/** idle → listening (mic) → thinking (STT+LLM+TTS) → speaking (playback) → idle */
export type VoiceStatus = 'idle' | 'listening' | 'thinking' | 'speaking';
export type VoiceLang = 'vi' | 'en';

export type VisualizerStyle = 'screen' | '3d';
export type VisualizerTheme = 'gold' | 'cyan' | 'cyber' | 'aurora' | 'sunset';

export interface VisualizerSettings {
  style: VisualizerStyle;
  theme: VisualizerTheme;
  size: number;
  gain: number;
  speed: number;
  glow: number;
  showCaptions: boolean;
  showPet: boolean;
  petScale: number;
}

export const VISUALIZER_DEFAULTS: VisualizerSettings = {
  style: 'screen',
  theme: 'gold',
  size: 150,
  gain: 1.4,
  speed: 1.0,
  glow: 20,
  showCaptions: true,
  showPet: true,
  petScale: 2.5,
};
