import { describe, expect, it } from 'vitest';

import { buildAnswerCard, buildToolCard, describeToolCall } from './tool-cards';

const base = { id: 'c1', timestamp: 1000, success: true, latency: 0.5 };

describe('buildToolCard', () => {
  it('muestra el resultado de la calculadora como cifra destacada', () => {
    const card = buildToolCard({
      ...base,
      tool: 'calculator',
      args: { expression: '345*27' },
      result: '9315.0',
    });
    expect(card).toMatchObject({ kind: 'metric', title: '345*27', value: '9315' });
  });

  it('convierte los resultados de búsqueda en una lista con enlaces', () => {
    const result = [
      '### Noticias UNAL',
      'Source: https://example.org/unal',
      'Summary: Inscripciones abiertas.',
      '',
      '### Otra nota',
      'Source: https://example.org/otra',
      'Summary: Segundo resumen.',
    ].join('\n');
    const card = buildToolCard({
      ...base,
      tool: 'web_search',
      args: { query: 'noticias unal' },
      result,
    });
    expect(card).toMatchObject({ kind: 'list', title: 'noticias unal' });
    expect(card?.kind === 'list' && card.items).toEqual([
      { title: 'Noticias UNAL', url: 'https://example.org/unal', snippet: 'Inscripciones abiertas.' },
      { title: 'Otra nota', url: 'https://example.org/otra', snippet: 'Segundo resumen.' },
    ]);
  });

  it('descarta enlaces que no son http(s)', () => {
    const card = buildToolCard({
      ...base,
      tool: 'web_search',
      args: { query: 'x' },
      result: '### Malo\nSource: javascript:alert(1)\nSummary: nada',
    });
    expect(card?.kind === 'list' && card.items[0].url).toBeUndefined();
  });

  it('muestra código y salida para el intérprete y la terminal', () => {
    const card = buildToolCard({
      ...base,
      tool: 'code_interpreter',
      args: { code: 'print(2+2)' },
      result: '4',
    });
    expect(card).toMatchObject({ kind: 'code', code: 'print(2+2)', output: '4' });
    expect(
      buildToolCard({ ...base, tool: 'shell_exec', args: { command: 'ls' }, result: 'a.txt' }),
    ).toMatchObject({ kind: 'code', code: 'ls', output: 'a.txt' });
  });

  it('no proyecta herramientas internas de razonamiento', () => {
    expect(buildToolCard({ ...base, tool: 'think', args: { thought: 'x' }, result: 'x' })).toBeNull();
  });

  it('usa una tarjeta de texto genérica para herramientas desconocidas y marca los fallos', () => {
    const card = buildToolCard({
      ...base,
      success: false,
      tool: 'get_weather',
      args: { location: 'Bogotá' },
      result: 'Falta la clave de API',
    });
    expect(card).toMatchObject({
      kind: 'text',
      title: 'get_weather',
      body: 'Falta la clave de API',
      failed: true,
    });
  });

  it('recorta resultados muy largos', () => {
    const card = buildToolCard({ ...base, tool: 'file_read', args: {}, result: 'x'.repeat(5000) });
    expect(card?.kind === 'text' && card.body.length).toBeLessThanOrEqual(1201);
  });
});

describe('describeToolCall', () => {
  it('resume la llamada con su argumento principal', () => {
    expect(describeToolCall('web_search', { query: 'clima bogotá', max_results: 5 })).toBe(
      'web_search · clima bogotá',
    );
    expect(describeToolCall('calculator', { expression: '2+2' })).toBe('calculator · 2+2');
    expect(describeToolCall('think', {})).toBe('think');
  });
});

describe('buildAnswerCard', () => {
  it('proyecta respuestas con código o tablas como documento', () => {
    const answer = 'Aquí está:\n```java\nint a = 1;\n```';
    expect(buildAnswerCard('a1', answer, 5, 'dame el código')).toMatchObject({
      kind: 'document',
      title: 'dame el código',
      markdown: answer,
    });
    expect(buildAnswerCard('a2', '| a | b |\n|---|---|\n| 1 | 2 |', 5, 'tabla')?.kind).toBe('document');
  });

  it('no proyecta respuestas cortas que basta con escuchar', () => {
    expect(buildAnswerCard('a3', 'Son las diez, señor.', 5, 'hora')).toBeNull();
  });

  it('proyecta respuestas largas aunque no tengan formato', () => {
    expect(buildAnswerCard('a4', 'palabra '.repeat(120), 5, 'texto')?.kind).toBe('document');
  });
});
