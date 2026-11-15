import { describe, expect, it } from 'vitest';
import {
  hasMalayalam,
  nextSpeechLang,
  pickMalayalamVoice,
  spokenReplySuffix,
  whisperLanguage,
} from './speechLang';

const voice = (name: string, lang: string) => ({ name, lang }) as SpeechSynthesisVoice;

describe('hasMalayalam', () => {
  it('detects a Malayalam reply', () => {
    expect(hasMalayalam('നമസ്കാരം, എനിക്ക് സഹായിക്കാം.')).toBe(true);
  });

  it('treats a Malayalam reply with a few English words as Malayalam', () => {
    expect(hasMalayalam('YouTube ഇപ്പോൾ തുറന്നിരിക്കുന്നു.')).toBe(true);
  });

  it('ignores English text', () => {
    expect(hasMalayalam('Opening YouTube now.')).toBe(false);
    expect(hasMalayalam('')).toBe(false);
  });
});

describe('whisperLanguage', () => {
  it('forces the chosen language and auto-detects otherwise', () => {
    expect(whisperLanguage('en')).toBe('en');
    expect(whisperLanguage('ml')).toBe('ml');
    expect(whisperLanguage('auto')).toBeUndefined();
  });
});

describe('spokenReplySuffix', () => {
  it('asks for a Malayalam reply when Malayalam is selected', () => {
    expect(spokenReplySuffix('ml', 'anything')).toMatch(/Malayalam script/);
  });

  it('asks for a Malayalam reply when Malayalam was heard in auto mode', () => {
    expect(spokenReplySuffix('auto', 'സമയം എത്രയായി?')).toMatch(/Malayalam script/);
  });

  it('keeps English when English is selected or heard', () => {
    expect(spokenReplySuffix('en', 'what time is it')).not.toMatch(/Malayalam/);
    expect(spokenReplySuffix('auto', 'what time is it')).not.toMatch(/Malayalam/);
  });

  it('always asks for a short spoken answer', () => {
    for (const lang of ['auto', 'en', 'ml'] as const) {
      expect(spokenReplySuffix(lang, 'hi')).toMatch(/two short spoken sentences/);
    }
  });
});

describe('pickMalayalamVoice', () => {
  it("prefers Edge's natural male Malayalam voice", () => {
    const voices = [
      voice('Microsoft Sobhana Online (Natural) - Malayalam (India)', 'ml-IN'),
      voice('Microsoft Midhun Online (Natural) - Malayalam (India)', 'ml-IN'),
      voice('Microsoft George - English (United Kingdom)', 'en-GB'),
    ];
    expect(pickMalayalamVoice(voices)?.name).toMatch(/Midhun/);
  });

  it('falls back to any Malayalam voice', () => {
    expect(pickMalayalamVoice([voice('Some voice', 'ml-IN')])?.name).toBe('Some voice');
  });

  it('returns null when the browser has none', () => {
    expect(pickMalayalamVoice([voice('Microsoft George', 'en-GB')])).toBeNull();
  });
});

describe('nextSpeechLang', () => {
  it('cycles auto -> English -> Malayalam -> auto', () => {
    expect(nextSpeechLang('auto')).toBe('en');
    expect(nextSpeechLang('en')).toBe('ml');
    expect(nextSpeechLang('ml')).toBe('auto');
  });
});
