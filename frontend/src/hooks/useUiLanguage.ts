import { useCallback, useState } from 'react';

export type UiLanguage = 'vi' | 'en';

export const UI_LANGUAGE_STORAGE_KEY = 'openjarvis.ui-language';

export function readUiLanguage(storage: Pick<Storage, 'getItem'>): UiLanguage {
  try {
    return storage.getItem(UI_LANGUAGE_STORAGE_KEY) === 'en' ? 'en' : 'vi';
  } catch {
    return 'vi';
  }
}

export function persistUiLanguage(
  storage: Pick<Storage, 'setItem'>,
  language: UiLanguage,
): void {
  try {
    storage.setItem(UI_LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}

export function useUiLanguage(): {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
} {
  const [language, setLanguageState] = useState<UiLanguage>(() => {
    if (typeof window === 'undefined') return 'vi';
    return readUiLanguage(window.localStorage);
  });

  const setLanguage = useCallback((nextLanguage: UiLanguage) => {
    setLanguageState(nextLanguage);
    if (typeof window !== 'undefined') {
      persistUiLanguage(window.localStorage, nextLanguage);
    }
  }, []);

  return { language, setLanguage };
}
