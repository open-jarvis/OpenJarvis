import { describe, expect, it } from 'vitest';
import { toSpeakableText } from './message-text';

describe('toSpeakableText', () => {
  it('removes emphasis markers so they are not read aloud', () => {
    expect(toSpeakableText('This is **very important** and *useful*.')).toBe(
      'This is very important and useful.',
    );
  });

  it('drops headings, bullets and numbering and pauses between lines', () => {
    const out = toSpeakableText('## Steps\n- first\n- second\n1. third');
    expect(out).toBe('Steps. first. second. third.');
  });

  it('keeps link text, drops URLs and inline code ticks', () => {
    expect(toSpeakableText('See [the docs](https://x.dev/a) and run `ls` now. https://x.dev')).toBe(
      'See the docs and run ls now.',
    );
  });

  it('replaces code blocks and removes emoji and think tags', () => {
    const out = toSpeakableText('<think>hmm</think>Done 😀\n```py\nprint(1)\n```');
    expect(out).toContain('code block omitted');
    expect(out).not.toMatch(/print|😀|think|hmm/);
  });

  it('keeps snake_case words intact', () => {
    expect(toSpeakableText('use file_read now')).toBe('use file_read now');
  });
});
