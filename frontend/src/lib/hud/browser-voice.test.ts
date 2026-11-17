import { describe, expect, it } from 'vitest';

import { pickSpanishVoice } from './browser-voice';

const voice = (name: string, lang: string, localService = false) => ({ name, lang, localService });

describe('pickSpanishVoice', () => {
  it('prefiere una voz neuronal masculina de Colombia', () => {
    const chosen = pickSpanishVoice([
      voice('Microsoft Sabina - Spanish (Mexico)', 'es-MX', true),
      voice('Microsoft Salome Online (Natural) - Spanish (Colombia)', 'es-CO'),
      voice('Microsoft Gonzalo Online (Natural) - Spanish (Colombia)', 'es-CO'),
      voice('Microsoft Alvaro Online (Natural) - Spanish (Spain)', 'es-ES'),
    ]);
    expect(chosen?.name).toBe('Microsoft Gonzalo Online (Natural) - Spanish (Colombia)');
  });

  it('una voz neuronal de otro país gana a una local de Colombia', () => {
    const chosen = pickSpanishVoice([
      voice('Voz local', 'es-CO', true),
      voice('Microsoft Jorge Online (Natural) - Spanish (Mexico)', 'es-MX'),
    ]);
    expect(chosen?.name).toBe('Microsoft Jorge Online (Natural) - Spanish (Mexico)');
  });

  it('acepta voces de Google y códigos con guion bajo', () => {
    const chosen = pickSpanishVoice([
      voice('Google US English', 'en-US'),
      voice('Google español de Estados Unidos', 'es_US'),
    ]);
    expect(chosen?.name).toBe('Google español de Estados Unidos');
  });

  it('devuelve null si no hay ninguna voz en español', () => {
    expect(pickSpanishVoice([voice('Microsoft David', 'en-US', true)])).toBeNull();
    expect(pickSpanishVoice([])).toBeNull();
  });
});
