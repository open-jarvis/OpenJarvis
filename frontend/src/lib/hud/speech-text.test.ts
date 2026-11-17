import { describe, expect, it } from 'vitest';

import { createSentenceSplitter, matchWakeWord } from './speech-text';

describe('matchWakeWord', () => {
  it('detecta la palabra al inicio y devuelve la orden limpia', () => {
    expect(matchWakeWord('Jarvis, ¿qué hora es?')).toEqual({
      matched: true,
      command: '¿qué hora es?',
    });
  });

  it('acepta saludos previos y variantes de transcripción', () => {
    expect(matchWakeWord('Oye Yarvis enciende las luces').command).toBe('enciende las luces');
    expect(matchWakeWord('Hey, Jarbis: abre el reporte').command).toBe('abre el reporte');
    expect(matchWakeWord('OK Járvis. Resume mi correo').command).toBe('Resume mi correo');
  });

  it('tolera las formas en que Whisper suele escribir el nombre', () => {
    for (const heard of ['Carvis', 'Harbys', 'Garvis', 'Charvis', 'Jervis', 'Yarbiz', 'Jarvys']) {
      expect(matchWakeWord(`${heard}, abre el informe`)).toEqual({
        matched: true,
        command: 'abre el informe',
      });
    }
  });

  it('no confunde palabras comunes parecidas', () => {
    for (const phrase of ['hay que hervir el agua', 'el servicio falló', 'un carbón caliente', 'tarde gris']) {
      expect(matchWakeWord(phrase).matched).toBe(false);
    }
  });

  it('detecta la palabra al final de la frase', () => {
    expect(matchWakeWord('¿Cuánto es dos más dos, Jarvis?')).toEqual({
      matched: true,
      command: '¿Cuánto es dos más dos?',
    });
  });

  it('devuelve orden vacía cuando solo se dice el nombre', () => {
    expect(matchWakeWord('Jarvis.')).toEqual({ matched: true, command: '' });
    expect(matchWakeWord('¿Jarvis?')).toEqual({ matched: true, command: '' });
  });

  it('ignora frases sin la palabra o con palabras que solo la contienen', () => {
    expect(matchWakeWord('qué hora es')).toEqual({ matched: false, command: '' });
    expect(matchWakeWord('el señor Jarvisson llamó')).toEqual({ matched: false, command: '' });
    expect(matchWakeWord('')).toEqual({ matched: false, command: '' });
  });
});

describe('createSentenceSplitter', () => {
  it('emite frases completas a medida que llega el texto', () => {
    const splitter = createSentenceSplitter();
    expect(splitter.push('Buenas noches, señor. Todos los ')).toEqual(['Buenas noches, señor.']);
    expect(splitter.push('sistemas están en línea. ¿Desea algo')).toEqual([
      'Todos los sistemas están en línea.',
    ]);
    expect(splitter.flush()).toEqual(['¿Desea algo']);
  });

  it('une fragmentos demasiado cortos con la frase siguiente', () => {
    const splitter = createSentenceSplitter();
    expect(splitter.push('Sí, señor. El resultado es nueve mil trescientos quince. ')).toEqual([
      'Sí, señor. El resultado es nueve mil trescientos quince.',
    ]);
  });

  it('no corta en decimales ni dentro de bloques de código', () => {
    const splitter = createSentenceSplitter();
    expect(splitter.push('El valor de pi es 3.14 aproximadamente, señor. ')).toEqual([
      'El valor de pi es 3.14 aproximadamente, señor.',
    ]);
    expect(splitter.push('Este es el código solicitado:\n```java\nint a = 1. ')).toEqual([
      'Este es el código solicitado:',
    ]);
    expect(splitter.push('\n```\nLo dejé en pantalla, señor. ')).toEqual([
      'Lo dejé en pantalla, señor.',
    ]);
  });

  it('quita el formato Markdown y los bloques de razonamiento', () => {
    const splitter = createSentenceSplitter();
    expect(
      splitter.push('<think>debo saludar</think>**Hola**, señor. Aquí tiene el [informe](http://x.y) listo. '),
    ).toEqual(['Hola, señor. Aquí tiene el informe listo.']);
    expect(splitter.flush()).toEqual([]);
  });

  it('espera a que cierre un bloque de razonamiento abierto', () => {
    const splitter = createSentenceSplitter();
    expect(splitter.push('<think>pensando. Mucho. ')).toEqual([]);
    expect(splitter.push('</think>Listo, señor, ya terminé el análisis. ')).toEqual([
      'Listo, señor, ya terminé el análisis.',
    ]);
  });

  it('flush devuelve vacío cuando no queda nada que decir', () => {
    const splitter = createSentenceSplitter();
    expect(splitter.flush()).toEqual([]);
  });
});
