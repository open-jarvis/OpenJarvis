import { describe, expect, it } from 'vitest';

import {
  persistUiLanguage,
  readUiLanguage,
  UI_LANGUAGE_STORAGE_KEY,
} from './useUiLanguage';

describe('useUiLanguage storage helpers', () => {
  it('defaults to Vietnamese for an empty or invalid value', () => {
    const storage = {
      getItem: () => null,
    };

    expect(readUiLanguage(storage)).toBe('vi');
    expect(readUiLanguage({ getItem: () => 'fr' })).toBe('vi');
  });

  it('reads English when persisted', () => {
    expect(readUiLanguage({ getItem: () => 'en' })).toBe('en');
  });

  it('persists the selected language under the stable key', () => {
    let saved: [string, string] | undefined;
    persistUiLanguage(
      {
        setItem: (key, value) => {
          saved = [key, value];
        },
      },
      'en',
    );

    expect(saved).toEqual([UI_LANGUAGE_STORAGE_KEY, 'en']);
  });

  it('falls back safely when storage is unavailable', () => {
    expect(readUiLanguage({ getItem: () => { throw new Error('blocked'); } })).toBe('vi');
    expect(() =>
      persistUiLanguage(
        { setItem: () => { throw new Error('blocked'); } },
        'vi',
      ),
    ).not.toThrow();
  });
});
