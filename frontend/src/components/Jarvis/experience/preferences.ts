import { useCallback, useState } from 'react';

export type JarvisMode = 'talk' | 'text';
export type AnimationQuality = 'off' | 'reduced' | 'standard' | 'high';
export type MouthMovement = 'off' | 'subtle' | 'normal';
export type MovementIntensity = 'very-low' | 'low' | 'standard' | 'high';

export interface JarvisPreferences {
  mode: JarvisMode;
  animationQuality: AnimationQuality;
  mouthMovement: MouthMovement;
  movementIntensity: MovementIntensity;
  reducedMotion: boolean;
  showAvatarInTextMode: boolean;
  developerMode: boolean;
  mockVoiceEnabled: boolean;
}

export const DEFAULT_JARVIS_PREFERENCES: JarvisPreferences = {
  mode: 'talk',
  animationQuality: 'standard',
  // The face remains dignified; speech is carried primarily by energy and particles.
  mouthMovement: 'subtle',
  movementIntensity: 'standard',
  reducedMotion: false,
  showAvatarInTextMode: true,
  developerMode: false,
  mockVoiceEnabled: false,
};

const PREFERENCES_KEY = 'openjarvis-ui-preferences-v1';

function loadPreferences(): JarvisPreferences {
  if (typeof window === 'undefined') return DEFAULT_JARVIS_PREFERENCES;
  try {
    const stored = window.localStorage.getItem(PREFERENCES_KEY);
    if (!stored) return DEFAULT_JARVIS_PREFERENCES;
    return { ...DEFAULT_JARVIS_PREFERENCES, ...JSON.parse(stored) as Partial<JarvisPreferences> };
  } catch {
    return DEFAULT_JARVIS_PREFERENCES;
  }
}

export function useJarvisPreferences() {
  const [preferences, setPreferencesState] = useState<JarvisPreferences>(loadPreferences);

  const setPreferences = useCallback((patch: Partial<JarvisPreferences>) => {
    setPreferencesState((current) => {
      const next = { ...current, ...patch };
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(next));
      }
      return next;
    });
  }, []);

  const resetPreferences = useCallback(() => {
    setPreferencesState(DEFAULT_JARVIS_PREFERENCES);
    if (typeof window !== 'undefined') window.localStorage.removeItem(PREFERENCES_KEY);
  }, []);

  return { preferences, setPreferences, resetPreferences };
}
